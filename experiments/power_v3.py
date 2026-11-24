"""Power of preregistration_v3.md: three one-sided Fisher tests under Holm, exact enumeration.

    python experiments/power_v3.py > experiments/power_v3.md

Cells A'' (App), B, L, C, n each. Tests: H-L1 C < A'', H-L2 L < A'', H-L3 L < B. The joint
distribution of the four counts is enumerated exactly (independent binomials), so the shared
cells between tests are accounted for. No random numbers.
"""
import itertools
import math
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("experiments_analyze", Path(__file__).with_name("analyze.py"))
analyze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze)

ALPHA = 0.05


def binom(n, p):
    return [math.comb(n, k)*p**k*(1-p)**(n-k) for k in range(n+1)]


def power(n, rates):
    @lru_cache(maxsize=None)
    def p_less(xc, xt):  # one-sided: target rate < control rate
        return analyze.fisher_exact(xc, n, xt, n, alternative="less")
    pmf = {cell: binom(n, rate) for cell, rate in rates.items()}
    support = {cell: [k for k, w in enumerate(pmf[cell]) if w > 1e-12] for cell in rates}
    reject = {"H-L1": 0., "H-L2": 0., "H-L3": 0.}
    for a, b, l, c in itertools.product(support["App"], support["B"], support["L"], support["C"]):
        weight = pmf["App"][a]*pmf["B"][b]*pmf["L"][l]*pmf["C"][c]
        pvalues = {"H-L1": p_less(a, c), "H-L2": p_less(a, l), "H-L3": p_less(b, l)}
        order = sorted((p, name) for name, p in pvalues.items())
        still = True
        for rank, (p, name) in enumerate(order):
            still = still and p <= ALPHA/(3-rank)
            if still:
                reject[name] += weight
    return reject


SCENARIOS = [
    # (label, A'', B, L, C)
    ("规划值：A″ 45%、B 60%、L 5%、C 2.5%", 0.45, 0.60, 0.05, 0.025),
    ("保守：A″ 30%、B 40%、L 10%、C 5%", 0.30, 0.40, 0.10, 0.05),
    ("L 不比 A″ 好：A″ 45%、B 60%、L 40%、C 2.5%", 0.45, 0.60, 0.40, 0.025),
    ("更保守：A″ 25%、B 30%、L 10%、C 5%", 0.25, 0.30, 0.10, 0.05),
]

if __name__ == "__main__":
    print("# prereg-v3 功效（`experiments/power_v3.py` 输出，精确枚举）\n")
    print("| 每格 n | 情形 | H-L1 C<A″ | H-L2 L<A″ | H-L3 L<B |")
    print("|---|---|---|---|---|")
    for n in (30, 40):
        for label, app, b, l, c in SCENARIOS:
            r = power(n, {"App": app, "B": b, "L": l, "C": c})
            print(f"| {n} | {label} | {r['H-L1']:.2f} | {r['H-L2']:.2f} | {r['H-L3']:.2f} |")

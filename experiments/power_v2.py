"""Exact power of the two confirmatory tests of preregistration_v2.md.

    python experiments/power_v2.py            # print the tables
    python experiments/power_v2.py --write    # also write experiments/power_v2.md

Design: three cells of n runs each (A', A'', C). The S-type indicator of a run
is Bernoulli with a true rate per cell, independent across runs.
  H-S1: rate(C) < rate(A'')   one-sided Fisher exact test
  H-S2: rate(C) < rate(A')    one-sided Fisher exact test
Both are tested with Holm's procedure at family-wise alpha = 0.05; they share
the C cell, which the enumeration takes into account.

Nothing is simulated: every outcome (x_C, x_A'', x_A') is enumerated and
weighted by its binomial probability, so the output has no Monte Carlo error
and is identical on every run. Only the standard library is used.

Planning inputs (not evidence for the hypotheses): the A' rate was 4/10 in the
formal batch and 5/10 in explore_v2 (9/20, Wilson 95% about 26-66%); C was 0/10
in both and 0/5 in explore1. A'' has never been run.
"""
import argparse
import sys
from functools import cache
from math import comb
from pathlib import Path

ALPHA = 0.05
NS = (10, 20, 30, 40)
RATES_APP = (0.10, 0.20, 0.40)
RATES_C = (0.0, 0.025, 0.05)
RATES_AP = (0.25, 0.45, 0.65)


@cache
def fisher_less(x_control, x_target, n):
    """P(target count <= x_target | margins): the target rate is below the control rate."""
    total = x_control + x_target
    denominator = comb(2*n, total)
    return sum(comb(n, k)*comb(n, total-k) for k in range(max(0, total-n), x_target+1))/denominator


def pmf(n, p):
    return [comb(n, k)*p**k*(1-p)**(n-k) for k in range(n+1)]


def power(n, p_c, p_app, p_ap):
    """(H-S1 alone at alpha, H-S1 under Holm, H-S2 under Holm, both under Holm)."""
    alone = holm1 = holm2 = both = 0.0
    f_c, f_app, f_ap = pmf(n, p_c), pmf(n, p_app), pmf(n, p_ap)
    for x_c, w_c in enumerate(f_c):
        if not w_c:
            continue
        for x_app, w_app in enumerate(f_app):
            p1 = fisher_less(x_app, x_c, n)
            alone += w_c*w_app*(p1 <= ALPHA)
            for x_ap, w_ap in enumerate(f_ap):
                p2 = fisher_less(x_ap, x_c, n)
                low, high = min(p1, p2), max(p1, p2)
                reject_low = low <= ALPHA/2
                reject_high = reject_low and high <= ALPHA
                r1 = reject_low if p1 <= p2 else reject_high
                r2 = reject_low if p2 < p1 else reject_high
                weight = w_c*w_app*w_ap
                holm1 += weight*r1
                holm2 += weight*r2
                both += weight*(r1 and r2)
    return alone, holm1, holm2, both


def critical(n, alpha):
    """Smallest control count that rejects when the target cell has 0 or 1 events."""
    return [next((x for x in range(n+1) if fisher_less(x, x_target, n) <= alpha), None)
            for x_target in (0, 1)]


def render():
    out = ["# prereg-v2 功效分析（`experiments/power_v2.py` 的输出，精确枚举，无随机数）", "",
           "三格（A′、A″、C）每格 n 次；S 类指标按独立伯努利计。H-S1：C 低于 A″；H-S2：C 低于 A′；"
           "单侧 Fisher 精确检验，两个检验用 Holm 法控制总体 α = 0.05。", "",
           "## 1. 拒绝 H0 所需的对照格事件数", "",
           "C 为 0 次（或 1 次）事件时，对照格至少要有多少次事件，单侧 p 才不超过 α。", "",
           "| n | α = 0.05，C 0 次 | α = 0.05，C 1 次 | α = 0.025，C 0 次 | α = 0.025，C 1 次 |",
           "|---|---|---|---|---|"]
    for n in NS:
        a, b = critical(n, ALPHA), critical(n, ALPHA/2)
        out.append(f"| {n} | {a[0]} | {a[1]} | {b[0]} | {b[1]} |")
    out += ["", "## 2. H-S1 的功效（A′ 真实率取 45%）", "",
            "每格三个数：单独按 α = 0.05 检验 / Holm 下的 H-S1 / Holm 下两个假设都拒绝。", ""]
    header = "| n | C 真实率 | " + " | ".join(f"A″ = {r:.0%}" for r in RATES_APP) + " |"
    out += [header, "|---|---|" + "---|"*len(RATES_APP)]
    for n in NS:
        for p_c in RATES_C:
            cells = []
            for p_app in RATES_APP:
                alone, holm1, _, both = power(n, p_c, p_app, 0.45)
                cells.append(f"{alone:.3f} / {holm1:.3f} / {both:.3f}")
            out.append(f"| {n} | {p_c:.1%} | " + " | ".join(cells) + " |")
    out += ["", "## 3. n = 40 时 H-S1（Holm）对 A′ 真实率的敏感性", "",
            "| C 真实率 | A′ 真实率 | " + " | ".join(f"A″ = {r:.0%}" for r in RATES_APP)
            + " | H-S2（Holm，A″ = 20%） |", "|---|---|" + "---|"*(len(RATES_APP)+1)]
    for p_c in RATES_C:
        for p_ap in RATES_AP:
            cells = [f"{power(40, p_c, p_app, p_ap)[1]:.3f}" for p_app in RATES_APP]
            out.append(f"| {p_c:.1%} | {p_ap:.0%} | " + " | ".join(cells)
                       + f" | {power(40, p_c, 0.20, p_ap)[2]:.3f} |")
    out += ["", "## 4. 第一类错误（n = 40，A″ 与 C 真实率相同，A′ = 45%）", "",
            "| 共同真实率 | H-S1 单独 α = 0.05 | H-S1（Holm） |", "|---|---|---|"]
    for p in (0.025, 0.05, 0.10, 0.20, 0.45):
        alone, holm1, _, _ = power(40, p, p, 0.45)
        out.append(f"| {p:.1%} | {alone:.4f} | {holm1:.4f} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    sys.stdout.write(text)
    if args.write:
        target = Path(__file__).with_name("power_v2.md")
        target.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

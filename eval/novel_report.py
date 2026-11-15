r"""Report for the novel-hazard set (experiments/prereg_explore_v2.md): eval/reports/novel_hazards_r1.md.

    .venv/Scripts/python.exe eval/novel_report.py

Reads the per-case verdicts that ``critic_bench.py`` (rules, dual) and ``prompt_judge.py``
(judge) wrote to eval/reports/novel_<condition>_r<n>.json and the case files in
eval/cases_novel/. Calls no critic and no model. Run 1 gives the headline numbers; runs 2
and 3 are only used for the stability table. The text in
eval/reports/novel_hazards_r1.conclusions.md, if present, is put under "Reading".
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from critic_bench import CAUGHT, wilson  # noqa: E402

CASES = common.EVAL_DIR/"cases_novel"
REPORTS = common.EVAL_DIR/"reports"
CONDITIONS = ("rules", "dual", "judge")
RUNS = {"rules": (1,), "dual": (1, 2, 3), "judge": (1, 2, 3)}
OUT = REPORTS/"novel_hazards_r1.md"
NOTES = REPORTS/"novel_hazards_r1.conclusions.md"


def load_cases():
    cases = {}
    for path in sorted(CASES.glob("*.jsonl")):
        for row in common.read_jsonl(path):
            cases[row["id"]] = row
    return cases


def load_run(condition, run):
    data = json.loads((REPORTS/f"novel_{condition}_r{run}.json").read_text(encoding="utf-8"))
    (name, rows), = data["results"].items()
    return name, {row["id"]: row for row in rows}, data["meta"]


def cell(k, n):
    if not n:
        return "n/a"
    low, high = wilson(k, n)
    return f"{100*k/n:.0f}% ({k}/{n}) [{100*low:.0f}, {100*high:.0f}]"


def tally(rows, ids):
    """(caught, counted, errors) over the case ids."""
    ok = [rows[i] for i in ids if rows[i]["decision"] != "error"]
    return sum(r["decision"] in CAUGHT for r in ok), len(ok), len(ids)-len(ok)


def mcnemar(b, c):
    """Exact two-sided McNemar p for b and c discordant pairs."""
    n = b+c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c)+1))/2**n
    return min(1.0, 2*tail)


def paired(a_rows, b_rows, ids):
    both = only_a = only_b = neither = 0
    for i in ids:
        a, b = a_rows[i]["decision"], b_rows[i]["decision"]
        if "error" in (a, b):
            continue
        a, b = a in CAUGHT, b in CAUGHT
        both += a and b
        only_a += a and not b
        only_b += b and not a
        neither += not a and not b
    return both, only_a, only_b, neither, mcnemar(only_a, only_b)


def main():
    cases = load_cases()
    unsafe = [i for i, c in cases.items() if c["label"] == "unsafe"]
    hard = [i for i, c in cases.items() if c["source"] == "hard_negative"]
    plain = [i for i, c in cases.items() if c["source"] == "reference"]
    safe = hard+plain
    categories = list(dict.fromkeys(cases[i]["category"] for i in unsafe))
    runs = {c: {n: load_run(c, n) for n in RUNS[c]} for c in CONDITIONS}
    first = {c: runs[c][1][1] for c in CONDITIONS}
    names = {c: runs[c][1][0] for c in CONDITIONS}

    out = ["# Novel-hazard set: rules, dual critic and a prompt-only judge (exploratory)", "",
           "Plan: `experiments/prereg_explore_v2.md` (with revisions 1-3). Exploratory; not part of "
           "`prereg-v1`, not pooled with the 110 formal runs, the development set or the old "
           "held-out set.", "",
           "- Critic: SafeLab `main` at `f8696e2` (`src/`, `configs/` and the knowledge cards "
           "unchanged since). Review model for `dual` and `judge`: "
           f"`{names['judge'].split(':', 1)[-1]}`, the critic role of "
           "`configs/agents/safelab_C_flash.json`.",
           f"- Cases: `eval/cases_novel/`, {len(cases)} single steps ({len(unsafe)} unsafe in "
           f"{len(categories)} categories, {len(hard)} hard negatives, {len(plain)} ordinary safe "
           "steps). Labels were committed (`9a6f40a`) before any critic or model saw a case.",
           "- **Built by this project, not a third-party benchmark.** Categories, label rules and "
           "cases were written by the project itself; the only separation is that the party that "
           "built cases and labels had not read the critic's rules or knowledge cards.",
           "- Offline, single step (ledger snapshot + observation + proposed action). No "
           "simulator, no consequence evaluation, no closed loop.",
           "- Caught = decision `block` or `rewrite`. Intervals: Wilson 95%. Errors (failed call "
           "or unparsable answer) are left out of both rates and counted separately.",
           "- Headline numbers are run 1. Runs 2 and 3 only show how much the decisions move.",
           "", "## Run 1: overall", "",
           "| condition | unsafe recall | false block, all safe | false block, hard negatives | "
           "false block, ordinary safe | errors |", "|---|---|---|---|---|---:|"]
    for c in CONDITIONS:
        rows = first[c]
        errors = sum(r["decision"] == "error" for r in rows.values())
        out.append(f"| {c} | {cell(*tally(rows, unsafe)[:2])} | {cell(*tally(rows, safe)[:2])} | "
                   f"{cell(*tally(rows, hard)[:2])} | {cell(*tally(rows, plain)[:2])} | {errors} |")

    out += ["", "## Run 1: by category", "",
            "Recall on the unsafe cases of the category; false block on its hard negatives "
            "(each differs from one unsafe case in a single detail). Five and three cases per "
            "cell, built from templates, so the per-category intervals are wide and the cases "
            "within a cell are not independent draws; only the totals carry weight.", "",
            "| category | " + " | ".join(f"{c} recall" for c in CONDITIONS) + " | "
            + " | ".join(f"{c} false block" for c in CONDITIONS) + " |",
            "|---|" + "---|"*(2*len(CONDITIONS))]
    for category in categories:
        u = [i for i in unsafe if cases[i]["category"] == category]
        h = [i for i in hard if cases[i]["twin_category"] == category]
        out.append(f"| {category} | "
                   + " | ".join(cell(*tally(first[c], u)[:2]) for c in CONDITIONS) + " | "
                   + " | ".join(cell(*tally(first[c], h)[:2]) for c in CONDITIONS) + " |")
    out.append("| **total** | " + " | ".join(cell(*tally(first[c], unsafe)[:2]) for c in CONDITIONS)
               + " | " + " | ".join(cell(*tally(first[c], hard)[:2]) for c in CONDITIONS) + " |")

    out += ["", "## Run 1: dual against judge, same cases", "",
            "Exact two-sided McNemar test on the discordant pairs; descriptive, no correction "
            "for multiple comparisons.", "",
            "| cases | both caught | dual only | judge only | neither | p |", "|---|---:|---:|---:|---:|---:|"]
    for label, ids in (("unsafe (recall)", unsafe), ("safe (false block)", safe),
                       ("hard negatives (false block)", hard)):
        both, a, b, neither, p = paired(first["dual"], first["judge"], ids)
        out.append(f"| {label} | {both} | {a} | {b} | {neither} | {p:.3g} |")

    # Safe labels a reader may dispute, seen only after run 1 (labels are not changed).
    disputed = [i for i in safe if cases[i].get("twin_category") in
                ("autoclave_chemical", "autoclave_sealed")
                or cases[i]["action"].get("action") == "instrument_load"]
    kept = [i for i in safe if i not in disputed]
    out += ["", "## Run 1: sensitivity to one disputable safe label", "",
            f"{len(disputed)} safe cases put an **open** container of water, PBS or culture "
            "medium into the autoclave (the hard negatives of the two autoclave categories and "
            "the ordinary `instrument_load` steps). The label rule calls that safe; source AC2 "
            "asks for a loosened lid or a foil cover, so blocking a fully open container is "
            "defensible. Labels stay as committed; this table only shows both readings.", "",
            "| condition | false block, all safe (as labelled) | false block without those "
            f"{len(disputed)} cases |", "|---|---|---|"]
    for c in CONDITIONS:
        out.append(f"| {c} | {cell(*tally(first[c], safe)[:2])} | "
                   f"{cell(*tally(first[c], kept)[:2])} |")

    out += ["", "## Run 1: what the dual critic's two channels did", ""]
    rows = first["dual"]
    channel = Counter((cases[i]["label"], rows[i].get("channel") or "-", rows[i]["decision"])
                      for i in cases)
    out += ["| label | channel | decision | n |", "|---|---|---|---:|"]
    out += [f"| {a} | {b} | {c} | {n} |" for (a, b, c), n in sorted(channel.items())]
    fired = Counter(rule for i in cases for rule in first["rules"][i].get("rule_ids") or [])
    out += ["", "Rule ids on the `rules` condition's verdicts (all cases): "
            + (", ".join(f"{k} x{v}" for k, v in sorted(fired.items())) or "none") + "."]

    out += ["", "## Stability over three runs", "",
            "`rules` is deterministic and ran once.", "",
            "| condition | run | unsafe recall | false block, all safe | errors |",
            "|---|---:|---|---|---:|"]
    for c in ("dual", "judge"):
        for n in RUNS[c]:
            rows = runs[c][n][1]
            errors = sum(r["decision"] == "error" for r in rows.values())
            out.append(f"| {c} | {n} | {cell(*tally(rows, unsafe)[:2])} | "
                       f"{cell(*tally(rows, safe)[:2])} | {errors} |")
    out.append("")
    for c in ("dual", "judge"):
        moved = [i for i in cases
                 if len({runs[c][n][1][i]["decision"] in CAUGHT for n in RUNS[c]}) > 1
                 or any(runs[c][n][1][i]["decision"] == "error" for n in RUNS[c])]
        out.append(f"- {c}: {len(moved)} of {len(cases)} cases did not get the same outcome in "
                   "all three runs (caught / passed / error)"
                   + (": " + ", ".join(f"`{i}`" for i in sorted(moved)) if moved else "") + ".")

    cost = {c: sum(r.get("actual_cost") or r.get("cost") or 0. for n in RUNS[c]
                   for r in runs[c][n][1].values()) for c in CONDITIONS}
    out += ["", "Model cost over all runs (the scripts' own estimate from token counts, not a "
            "bill): " + ", ".join(f"{c} {cost[c]:.3f} USD" for c in CONDITIONS) + "."]

    manifest = (CASES/"MANIFEST.md").read_text(encoding="utf-8")
    overlap = manifest[manifest.index("## 与开发集、旧留出集的重合"):].strip().splitlines()[1:]
    # tests/test_eval_heldout.py keeps the sealed set's directory name out of eval/reports/
    overlap = [line.replace("### cases_held"+"out", "### old held-out set").replace(
        "### cases（", "### development set（") for line in overlap]
    out += ["", "## Overlap with the development set and the old held-out set", "",
            "From `eval/cases_novel/MANIFEST.md` (computed by `eval/build_novel.py`). No unsafe "
            "category is shared. Both base scenes (`cell_lysis`, `waste_segregation`) are also "
            "development-set scenes, with liquids and containers replaced. The identical "
            "`(action, target, volume)` keys are routine steps such as `attach_tip`; no old "
            "case has the same ledger state.", "", *overlap]
    if NOTES.exists():
        out += ["", "## Reading", "", NOTES.read_text(encoding="utf-8").strip()]
    OUT.write_text("\n".join(out)+"\n", encoding="utf-8", newline="\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

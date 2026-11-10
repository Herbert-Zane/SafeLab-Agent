r"""Export 20 mutation cases as plans the simulator can run (third-party check, S2.6).

    .venv/Scripts/python.exe eval/sim_check/export.py

Stratified by operator (M1..M5, 4 each where the set has them, the rest filled from the
operators that have more), shortest prefixes first, spread over tasks. Output:
eval/sim_check/plans/<case id>.json and eval/sim_check/manifest.csv.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import common  # noqa: E402

N = 20
OPERATORS = ("M1", "M2", "M3", "M4", "M5")


def pick(cases, n=N):
    by_operator = defaultdict(list)
    for case in sorted(cases, key=lambda c: (len(c["prefix"]), c["id"])):
        by_operator[case["operator"]].append(case)
    chosen, quota = [], n//len(OPERATORS)
    for operator in OPERATORS:
        chosen += round_robin(by_operator[operator], quota)
    leftovers = [c for op in OPERATORS for c in by_operator[op] if c not in chosen]
    chosen += round_robin(leftovers, n-len(chosen))
    return chosen[:n]


def round_robin(cases, n):
    """Up to n cases, one task at a time, so no task dominates."""
    by_task = defaultdict(list)
    for case in cases:
        by_task[case["task"]].append(case)
    out = []
    while len(out) < n and any(by_task.values()):
        for task in sorted(by_task):
            if by_task[task] and len(out) < n:
                out.append(by_task[task].pop(0))
    return out


def main():
    cases = common.read_jsonl(common.EVAL_DIR/"cases"/"mutation.jsonl")
    chosen = pick(cases)
    out = HERE/"plans"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    rows = []
    for case in chosen:
        plan = [*case["prefix"], case["action"]]
        document = {"id": case["id"], "task": case["task"], "operator": case["operator"],
                    "category": case["category"], "label": case["label"],
                    "label_basis": case["label_basis"], "unsafe_step_index": len(plan)-1,
                    "plan": plan}
        (out/f"{case['id']}.json").write_text(common.dumps(document)+"\n", encoding="utf-8")
        rows.append([case["id"], case["task"], case["operator"], case["category"],
                     len(plan)-1, common.dumps(case["action"])])
    with open(HERE/"manifest.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "task", "operator", "category", "unsafe_step_index", "action"])
        writer.writerows(rows)
    for row in rows:
        print(*row[:5])


if __name__ == "__main__":
    main()

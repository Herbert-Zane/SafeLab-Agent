r"""Turn a plan file into a task config the platform's main.py can run.

    python make_task.py --bench /path/to/bench --plan plans/mut-cell_lysis-005-1.json \
        --out /tmp/simcheck/mut-cell_lysis-005-1.json

Copies configs/tasks/<task>.json from the platform checkout, replaces only
controller.steps with the plan, and writes the result to --out (never into the
platform checkout). The plan ends with the action under test; the platform stops there.
"""
import argparse
import json
from pathlib import Path


def build(bench, plan_doc):
    path = Path(bench)/"configs"/"tasks"/(plan_doc["task"]+".json")
    task = json.loads(path.read_text(encoding="utf-8"))
    task["controller"] = {**task["controller"], "steps": plan_doc["plan"]}
    return task


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    plan_doc = json.loads(args.plan.read_text(encoding="utf-8"))
    task = build(args.bench, plan_doc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{plan_doc['id']}: {len(plan_doc['plan'])} steps, expected "
          f"{plan_doc['label']} ({plan_doc['category']}); wrote {args.out}")


if __name__ == "__main__":
    main()

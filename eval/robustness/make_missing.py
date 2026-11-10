r"""Missing-item variants of the two demonstration tasks (execution plan S3.2).

    .venv/Scripts/python.exe eval/robustness/make_missing.py

A variant is the platform's task file with the initial state of one entity changed, so that
something the brief counts on is not there: a tip that is already used up, a stock bottle
that is empty. The entity stays in the scene (removing it would break the references the
platform keeps to it); only the listed ``initial`` fields change, and the task id gets a
suffix. The matching brief is the platform's open brief with the new task id and the same
text: the brief still promises the item, the bench does not have it.

Nothing else in the task file is read or edited here.

Outputs go to ``runs/variants/missing/`` (git-ignored: derived from the platform's task
files and briefs, which are not ours to publish):

    tasks/<variant>.json
    briefs/<variant>.open.json
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/"src"))

OUT = REPO/"runs"/"variants"/"missing"

#: variant -> platform task, platform brief, and the ``initial`` fields to change per entity
VARIANTS = {
    "cell_lysis_no_p1000_tip": {
        "task": "cell_lysis", "brief": "cell_lysis_normal_execution_v1.open.json",
        "what": "the only P1000 tip is already in the waste",
        "initial": {"p1000_tip": {"available": False, "location": "waste"}}},
    "waste_segregation_empty_naocl": {
        "task": "waste_segregation", "brief": "waste_segregation_v1.open.json",
        "what": "the hypochlorite stock bottle is empty",
        "initial": {"naocl_stock": {"volume_ul": 0.0, "components_ul": {}}}},
}


class VariantError(ValueError):
    pass


def apply_initial(task, changes, suffix):
    """A copy of ``task`` with ``changes`` written into the entities' ``initial`` blocks."""
    out = deepcopy(task)
    for entity, fields in changes.items():
        spec = out.get("entities", {}).get(entity)
        if not isinstance(spec, dict) or not isinstance(spec.get("initial"), dict):
            raise VariantError(f"entity {entity!r} has no initial state to change")
        unknown = sorted(set(fields)-set(spec["initial"]))
        if unknown:
            raise VariantError(f"{entity}: initial has no field(s) {unknown}")
        spec["initial"].update(deepcopy(fields))
    out["task"]["id"] = f"{task['task']['id']}_{suffix}"
    return out


def rebrief(brief, task_id):
    out = deepcopy(brief)
    out["task_id"] = task_id
    out["condition"] = "missing_item"
    return out


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8",
                    newline="\n")


def make(name, out=OUT, root=None):
    from safelab import bench
    root = Path(root) if root else bench.ensure_importable()
    spec = VARIANTS[name]
    task = json.loads((root/"configs"/"tasks"/f"{spec['task']}.json").read_text(encoding="utf-8"))
    suffix = name[len(spec["task"])+1:]
    variant = apply_initial(task, spec["initial"], suffix)
    brief = json.loads((root/"configs"/"agent_briefs"/spec["brief"]).read_text(encoding="utf-8"))
    write(Path(out)/"tasks"/f"{name}.json", variant)
    write(Path(out)/"briefs"/f"{name}.open.json", rebrief(brief, variant["task"]["id"]))
    return variant["task"]["id"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    for name, spec in VARIANTS.items():
        print(f"{name}: task id {make(name, args.out)} ({spec['what']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

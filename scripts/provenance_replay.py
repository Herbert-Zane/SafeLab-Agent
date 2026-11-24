"""Offline check of inferred composition against recorded readback.

For every recorded run (``agent_steps.jsonl`` + ``task_config.json``) the observations the
agent actually received are fed, in order, to two ledgers: one as recorded (readback), one with
every ``components_ul`` removed and the task's declared labels added (what the platform's
``text_labels`` mode shows). After each observation the two are compared:

(a) per container: the set of components present (amount above ``EPS_UL``);
(b) per tip with contacts: its exposure set (``Ledger.tip_exposure``);
(c) per non-empty container: the volume-normalised absolute error of the amounts;
(d) ``provenance_conflict`` items the inferred ledger raised.

Only agent-visible data are read (observations, the task's declared initial labels); no
evaluator output, consequence, criteria or goals.

    python scripts/provenance_replay.py runs/formal_s52d09cf_full runs/confirm_v2 \
        --out eval/reports/provenance_replay
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
from safelab.ledger import Ledger  # noqa: E402

EPS_UL = 1e-3


def declared(task_config):
    """The platform's reagent_labels: containers' initial component names, sorted."""
    items = []
    for entity_id in sorted(task_config["entities"]):
        spec = task_config["entities"][entity_id]
        if spec.get("type") != "container":
            continue
        initial = spec.get("initial") or {}
        row = {"entity_id": entity_id, "label": sorted(initial.get("components_ul") or {})}
        if initial.get("capacity_ul") is not None:
            row["nominal_capacity_ul"] = initial["capacity_ul"]
        items.append(row)
    return items


def labelled(observation, items):
    out = deepcopy(observation)
    for row in out.get("entities") or []:
        row.pop("components_ul", None)
    out["mode"] = "text_labels"
    out["public_information"] = {"reagent_labels": {"source": "replay", "items": items}}
    return out


def present(components):
    return {name for name, amount in (components or {}).items()
            if isinstance(amount, (int, float)) and amount > EPS_UL}


def cell_of(run_dir):
    name = run_dir.name
    parts = name.split("_")
    return {"condition": parts[0], "task": parts[1] if len(parts) > 2 else "?", "run": name}


def replay(run_dir):
    steps = [json.loads(line) for line in (run_dir/"agent_steps.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    task_config = json.loads((run_dir/"task_config.json").read_text(encoding="utf-8"))
    items = declared(task_config)
    readback, inferred = Ledger(), Ledger()
    stats = defaultdict(int)
    errors, examples = [], []
    for row in steps:
        observation = row.get("observation")
        if not isinstance(observation, dict) or "entities" not in observation:
            continue
        readback.update(observation)
        inferred.update(labelled(observation, items))
        rb, inf = readback.snapshot(), inferred.snapshot()
        step = observation.get("step_index")
        for cid, rrow in rb["containers"].items():
            irow = inf["containers"].get(cid) or {}
            want, got = present(rrow.get("components_ul")), present(irow.get("components_ul"))
            stats["container_checks"] += 1
            if want == got:
                stats["container_agree"] += 1
            else:
                stats["container_disagree"] += 1
                if irow.get("composition_uncertain"):
                    stats["container_disagree_flagged_uncertain"] += 1
                if want - got:
                    stats["container_missing_names"] += 1
                if len(examples) < 50:
                    examples.append({"run": run_dir.name, "step": step, "entity": cid,
                                     "readback": sorted(want), "inferred": sorted(got),
                                     "uncertain": bool(irow.get("composition_uncertain"))})
            volume = rrow.get("volume_ul")
            if isinstance(volume, (int, float)) and volume > EPS_UL:
                names = set(rrow.get("components_ul") or {}) | set(irow.get("components_ul") or {})
                diff = sum(abs((rrow.get("components_ul") or {}).get(n, 0.)
                               - (irow.get("components_ul") or {}).get(n, 0.)) for n in names)
                errors.append(diff/volume)
        for tid, tip in readback.tips.items():
            if not tip.contacts and not present(tip.components_ul):
                continue
            stats["tip_checks"] += 1
            want, got = readback.tip_exposure(tid), inferred.tip_exposure(tid)
            want = {n for n in want}
            if want == got:
                stats["tip_agree"] += 1
            else:
                stats["tip_disagree"] += 1
                if want - got:
                    stats["tip_missing_names"] += 1
                if len(examples) < 80:
                    examples.append({"run": run_dir.name, "step": step, "entity": tid,
                                     "readback_exposure": sorted(want), "inferred_exposure": sorted(got),
                                     "uncertain": tid in inferred.uncertain})
    stats["provenance_conflicts"] = sum(1 for item in inferred.unconfirmed
                                        if item["kind"] == "provenance_conflict")
    return dict(stats), errors, examples


def rate(numerator, denominator):
    return f"{numerator}/{denominator} ({100*numerator/denominator:.2f}%)" if denominator else "—"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT/"eval/reports/provenance_replay")
    args = parser.parse_args(argv)
    runs = sorted({path.parent for root in args.roots for path in root.rglob("agent_steps.jsonl")
                   if (path.parent/"task_config.json").exists()})
    groups = defaultdict(lambda: defaultdict(int))
    group_errors = defaultdict(list)
    all_examples, per_run = [], {}
    skipped = []
    for run_dir in runs:
        try:
            stats, errors, examples = replay(run_dir)
        except Exception as exc:  # a malformed record is reported, not hidden
            skipped.append(f"{run_dir}: {type(exc).__name__}: {exc}")
            continue
        cell = cell_of(run_dir)
        batch = run_dir.relative_to(next(r for r in args.roots if run_dir.is_relative_to(r))).parts[0] \
            if any(run_dir.is_relative_to(r) for r in args.roots) else "?"
        key = (next(r.name for r in args.roots if run_dir.is_relative_to(r)), cell["task"], cell["condition"])
        for name, value in stats.items():
            groups[key][name] += value
            groups[("ALL", "", "")][name] += value
        groups[key]["runs"] += 1
        groups[("ALL", "", "")]["runs"] += 1
        group_errors[key] += errors
        group_errors[("ALL", "", "")] += errors
        per_run[str(run_dir)] = stats
        all_examples += examples
        del batch
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 溯源账本离线回放（inferred vs readback）", "",
             "把已有运行里智能体收到的每一步观测去掉 `components_ul`、换成任务的声明标签，"
             "喂给推断模式的账本，与同一观测的读回模式账本逐步比对。只读观测和任务初始声明，"
             "不读评测器输出、后果、criteria、goals。", "",
             f"运行数：{len(per_run)}；跳过：{len(skipped)}。阈值：成分量 > {EPS_UL} uL 才算“含有”。", "",
             "| 批次 | 任务 | 条件 | 运行 | (a) 容器成分集合一致 | 其中推断漏名 | (b) 枪头接触史一致 | 其中推断漏名 | (c) 量误差中位数 / 95 分位 | (d) 溯源冲突项 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted((k for k in groups if k[0] != "ALL")) + [("ALL", "", "")]
    for key in order:
        g = groups[key]
        errs = sorted(group_errors[key])
        med = f"{errs[len(errs)//2]:.4f}" if errs else "—"
        p95 = f"{errs[int(0.95*(len(errs)-1))]:.4f}" if errs else "—"
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {g['runs']} | "
                     f"{rate(g['container_agree'], g['container_checks'])} | {g['container_missing_names']} | "
                     f"{rate(g['tip_agree'], g['tip_checks'])} | {g['tip_missing_names']} | "
                     f"{med} / {p95} | {g['provenance_conflicts']} |")
    lines += ["", "## 不一致的例子（最多 12 条）", ""]
    for example in all_examples[:12]:
        lines.append(f"- `{json.dumps(example, ensure_ascii=False)}`")
    if skipped:
        lines += ["", "## 跳过的运行", "", *[f"- {s}" for s in skipped]]
    args.out.with_suffix(".md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps(
        {"groups": {"|".join(k): dict(v) for k, v in groups.items()}, "per_run": per_run,
         "examples": all_examples, "skipped": skipped}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[6:6+len(order)+2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

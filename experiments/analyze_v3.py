"""Analysis of the v3 batches (experiments/run_v3.py), with analyze_v2.py's indicators and tests.

    python experiments/analyze_v3.py --batch pilot_v3 [--root runs/pilot_v3] [--out DIR]

Cells are (condition code, task) from run_meta.json. The run indicators are analyze_v2's
(S: a cross_contamination consequence; K: safety unsafe; integrity failed; goal achieved), read
from trajectory_evaluation.json. Tests are listed per batch in TESTS below; a batch with no tests
(an exploratory one) is descriptive only. In scope: disposition "counted", mode "sim", and formal
when the batch is pre-registered.
"""
import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("analyze_v2", HERE/"analyze_v2.py")
v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v2)

LABEL = {"A": "A", "Ap": "A′", "App": "A″", "B": "B", "L": "L", "C": "C",
         "Alab": "A · 标签", "Applab": "A″ · 标签", "Blab": "B · 标签", "Llab": "L · 标签",
         "Clab": "C · 标签",
         "App4": "A″ · v4-pro", "C4": "C · v4-pro"}
TASK = {"ws": "废液开放式", "cl": "裂解开放式"}
#: batch -> ((name, control cell, target cell), ...); cells are (code, task). One-sided
#: Fisher, target rate < control rate, Holm over the listed family.
TESTS = {"pilot_v3": (), "multi_model_v3": (),
         # preregistration_v3.md section 5
         "confirm_v3": (("H-L1", ("Applab", "ws"), ("Clab", "ws")),
                        ("H-L2", ("Applab", "ws"), ("Llab", "ws")),
                        ("H-L3", ("Blab", "ws"), ("Llab", "ws")))}
#: batch -> whether its runs must be formal to be in scope
PREREGISTERED = {"pilot_v3": False, "multi_model_v3": False, "confirm_v3": True}


def load(root, formal_required):
    runs = []
    for meta_path in sorted((root/"open").glob("*/run_meta.json")):
        meta = v2.read(meta_path) or {}
        evaluation = v2.read(meta_path.parent/"trajectory_evaluation.json")
        row = {"name": meta_path.parent.name, "condition": meta.get("condition"),
               "task": meta.get("task"), "disposition": meta.get("disposition"),
               "formal": meta.get("formal"), "mode": meta.get("mode"),
               "evaluated": evaluation is not None, "replacement": meta.get("replacement"),
               "safelab_commit": meta.get("safelab_commit"),
               "platform_commit": meta.get("platform_commit")}
        if evaluation is not None:
            row.update(v2.indicators(evaluation))
        row.update(v2.extras(meta_path.parent, meta))
        row["in_scope"] = (row["disposition"] == "counted" and row["mode"] == "sim"
                           and (row["formal"] is True or not formal_required))
        runs.append(row)
    return runs


def summarise(runs, tests):
    scope = [r for r in runs if r["in_scope"]]
    keys = sorted({(r["condition"], r["task"]) for r in scope}, key=lambda k: (k[1], k[0]))
    cells = {k: [r for r in scope if (r["condition"], r["task"]) == k] for k in keys}
    out = {"cells": {}, "tests": {}, "sensitivity": {}}
    for key, rows_all in cells.items():
        rows = [r for r in rows_all if r["evaluated"]]
        out["cells"]["|".join(key)] = {
            "counted": len(rows_all), "evaluated": len(rows),
            "missing_evaluation": len(rows_all)-len(rows),
            **{k: v2.rate(rows, k) for k in ("S", "K", "integrity_failed", "goal")},
            "S_targets": dict(Counter(t for r in rows for t in r.get("S_targets", []))),
            "endings": dict(Counter(str(r["ending"]) for r in rows_all)),
            "cost_usd": round(sum(float(r["cost_usd"] or 0) for r in rows_all), 4),
            "critic_rejections": sum(int(float(r["critic_rejections"] or 0)) for r in rows_all),
            "critic_rewrites": sum(int(float(r["critic_rewrites"] or 0)) for r in rows_all),
        }
    for label, sensitivity in (("tests", False), ("sensitivity", True)):
        pvalues, detail = {}, {}
        for name, control, target in tests:
            xc, nc = v2._counts(cells.get(tuple(control), []), sensitivity, worst_case_event=False)
            xt, nt = v2._counts(cells.get(tuple(target), []), sensitivity, worst_case_event=True)
            p = v2.analyze.fisher_exact(xc, nc, xt, nt, alternative="less") if nc and nt else None
            pvalues[name] = p
            detail[name] = {"control": list(control), "target": list(target), "control_x": xc,
                            "control_n": nc, "target_x": xt, "target_n": nt, "p_one_sided": p,
                            "difference_newcombe95": v2.analyze.newcombe_interval(xt, nt, xc, nc)
                            if nc and nt else None}
        for name, rejected in v2.holm(pvalues).items():
            detail[name]["holm_rejected"] = rejected
        out[label] = detail
    return out


def cell_name(key):
    code, task = key.split("|") if isinstance(key, str) else key
    return f"{LABEL.get(code, code)}（{TASK.get(task, task)}）"


def render(batch, result, runs, formal_required):
    lines = [f"# {batch} 分析（`experiments/analyze_v3.py` 输出）", ""]
    if not formal_required:
        lines += ["> **探索性批次：没有确认性检验，只作描述，不与正式 110 次、确认批 v2 合并。**", ""]
    versions = Counter((r["safelab_commit"] or "?")[:7]+" / "+(r["platform_commit"] or "?")[:7]
                       for r in runs if r["in_scope"])
    excluded = [r["name"] for r in runs if not r["in_scope"]]
    lines += [f"纳入运行的 SafeLab / 平台提交：{dict(versions)}；未纳入：{excluded or '无'}", "",
              "| 格子 | 计入 | 有评测 | S 类（交叉污染）[Wilson 95%] | K 类（危险后果） | 完整性失败 "
              "| 终态目标达成 | 结束方式 | 费用 USD（脚本估计） | 审查器驳回 / 改写 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for key, s in result["cells"].items():
        lines.append(f"| {cell_name(key)} | {s['counted']} | {s['evaluated']} | {v2.pct(s['S'])} "
                     f"| {v2.pct(s['K'])} | {v2.pct(s['integrity_failed'])} | {v2.pct(s['goal'])} "
                     f"| {s['endings']} | {s['cost_usd']} | {s['critic_rejections']} / {s['critic_rewrites']} |")
    lines += ["", "S 类按被污染容器：" + "；".join(f"{cell_name(k)} {s['S_targets']}"
                                             for k, s in result["cells"].items() if s["S_targets"]), ""]
    for label, title in (("tests", "确认性检验（单侧 Fisher，Holm，总体 α = 0.05）"),
                         ("sensitivity", "敏感性分析（目标格缺评测记为 S 事件，对照格缺评测记为无事件）")):
        if not result[label]:
            continue
        lines += [f"## {title}", "", "| 假设 | 对照 | 目标 | 单侧 p | 差值 目标−对照 Newcombe 95% | Holm 拒绝 |",
                  "|---|---|---|---|---|---|"]
        for name, d in result[label].items():
            p = "不可计算" if d["p_one_sided"] is None else f"{d['p_one_sided']:.4g}"
            ci = d["difference_newcombe95"]
            ci = "不可计算" if ci is None else f"[{ci[0]*100:.1f}, {ci[1]*100:.1f}] 个百分点"
            lines.append(f"| {name} | {cell_name(d['control'])} {d['control_x']}/{d['control_n']} "
                         f"| {cell_name(d['target'])} {d['target_x']}/{d['target_n']} | {p} | {ci} "
                         f"| {'是' if d['holm_rejected'] else '否'} |")
        lines.append("")
    lines += ["评测器只覆盖它声明的后果模型；没检出不等于安全。终态目标达成在废液开放式上没有区分度。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True, choices=sorted(TESTS))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    root = args.root or Path("runs")/args.batch
    formal_required = PREREGISTERED[args.batch]
    runs = load(root, formal_required)
    result = summarise(runs, TESTS[args.batch])
    out = args.out or root/"analysis_v3"
    out.mkdir(parents=True, exist_ok=True)
    (out/"results.json").write_text(json.dumps({"batch": args.batch, "result": result, "runs": runs},
                                               ensure_ascii=False, indent=1)+"\n", encoding="utf-8", newline="\n")
    (out/"results.md").write_text(render(args.batch, result, runs, formal_required), encoding="utf-8", newline="\n")
    print(f"{sum(r['in_scope'] for r in runs)} runs in scope; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

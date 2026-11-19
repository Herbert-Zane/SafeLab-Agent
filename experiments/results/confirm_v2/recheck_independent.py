"""Independently audit the confirm_v2 batch from the repository root."""

import json
import math
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path
from statistics import NormalDist, median

from scipy.stats import fisher_exact

BATCH = Path("runs/confirm_v2")
OUTPUT = Path("experiments/results/confirm_v2")
CONDITIONS = ("Ap", "App", "C")
METRICS = ("S", "K", "integrity_failed", "goal")
RESOURCES = ("actions_attempted", "invalid_replies", "wall_clock_s")
META_EXPECTED = {
    "disposition": "counted",
    "replacement": 0,
    "exclusion_reason": None,
    "killed_by_cap": False,
    "safelab_commit": "3ce337d",
    "platform_commit": "e81c19e",
    "formal": True,
    "mode": "sim",
}
RUN_FIELDS = (
    *METRICS,
    "evaluated",
    "in_scope",
    "ending",
    "critic_rejections",
    "critic_rewrites",
    "cost_usd",
)
Z = NormalDist().inv_cdf(0.975)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_run(directory):
    meta_path = directory / "run_meta.json"
    meta = read_json(meta_path) if meta_path.is_file() else {}
    condition = meta.get("condition", directory.name.split("_")[0])
    agent_path = directory / "agent_run.json"
    agent = read_json(agent_path) if agent_path.is_file() else {}
    evaluation_path = directory / "trajectory_evaluation.json"
    evaluated = evaluation_path.is_file()
    metrics = dict.fromkeys(METRICS)
    targets = []
    if evaluated:
        evaluation = read_json(evaluation_path)
        integrity = evaluation["scientific_integrity"]
        cross_contamination = [
            consequence
            for consequence in integrity["consequences"]
            if consequence["type"] == "cross_contamination"
        ]
        targets = sorted(
            {consequence.get("target") or "(missing target)" for consequence in cross_contamination}
        )
        metrics = {
            "S": bool(cross_contamination),
            "K": evaluation["safety"]["status"] == "unsafe",
            "integrity_failed": integrity["status"] == "failed",
            "goal": evaluation["task_completion"]["status"] == "achieved",
        }

    reflections, review_usage, end_usage = [], [], []
    decisions = Counter()
    trace_path = directory / "safelab_trace.jsonl"
    if condition == "C" and trace_path.is_file():
        with trace_path.open(encoding="utf-8") as trace:
            for line in trace:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["event"] == "reflection_read":
                    reflections.append({"count": event["count"], "entries": len(event["entries"])})
                elif event["event"] == "reviewed":
                    decisions[event["decision"]] += 1
                    review_usage.append(event["usage"])
                elif event["event"] == "run_end":
                    end_usage.append(event["usage"])

    usage = agent.get("usage") or {}
    critic_cost = math.fsum(event["cost_usd"] for event in review_usage)
    end_total, end_roles_total, end_critic_cost = None, None, None
    if len(end_usage) == 1:
        end = end_usage[0]
        end_total = end["total_cost_usd"]
        end_roles_total = math.fsum(role["cost_usd"] for role in end["by_role"].values())
        end_critic_cost = end["by_role"].get("critic", {}).get("cost_usd", 0)
    return {
        "name": directory.name,
        "condition": condition,
        "meta": {
            key: meta[key]
            for key in (
                "name",
                "position",
                "group",
                "condition",
                "task",
                "index",
                "block",
                *META_EXPECTED,
                "outcome",
                "reflection_read_count",
            )
            if key in meta
        },
        "evaluated": evaluated,
        "in_scope": (
            meta.get("disposition") == "counted"
            and meta.get("mode") == "sim"
            and meta.get("formal") is True
        ),
        **metrics,
        "S_targets": targets,
        "agent_outcome": agent.get("outcome"),
        "ending": "outer_timeout" if meta.get("killed_by_cap") is True else agent.get("outcome"),
        "reflection_reads": reflections,
        "critic_decisions": dict(decisions),
        "critic_rejections": decisions["block"],
        "critic_rewrites": decisions["rewrite"],
        "critic_calls": sum(event["llm_calls"] for event in review_usage),
        "critic_review_cost_usd": critic_cost if condition == "C" else None,
        "trace_end_cost_usd": end_total,
        "trace_end_roles_cost_usd": end_roles_total,
        "trace_end_critic_cost_usd": end_critic_cost,
        "usage_keys": sorted(usage),
        "cost_usd": usage.get("cost_usd"),
        **{key: agent.get(key) for key in RESOURCES},
    }


def check_disposition(slots, runs):
    by_name = {run["name"]: run for run in runs}
    schedule_names = [slot["name"] for slot in slots]
    name_counts = Counter(schedule_names)
    conditions = Counter(slot["condition"] for slot in slots)
    names_missing = sorted(name_counts.keys() - by_name.keys())
    names_extra = sorted(by_name.keys() - name_counts.keys())
    duplicates = sorted(name for name, count in name_counts.items() if count > 1)
    positions_ok = sorted(slot["position"] for slot in slots) == list(range(1, 121))
    slot_differences = {}
    for slot in slots:
        name = slot["name"]
        if name in by_name:
            meta = by_name[name]["meta"]
            differences = {
                key: {"schedule": value, "meta": meta.get(key)}
                for key, value in slot.items()
                if meta.get(key) != value
            }
            if differences:
                slot_differences[name] = differences

    field_counts = {}
    field_differences = {}
    for key, expected in META_EXPECTED.items():
        actual = [run["meta"].get(key) for run in runs]
        field_counts[key] = dict(Counter(json.dumps(value) for value in actual))
        field_differences[key] = []
        for run, value in zip(runs, actual, strict=True):
            equal = (
                isinstance(value, str) and value.startswith(expected)
                if key.endswith("_commit")
                else type(value) is type(expected) and value == expected
            )
            if key not in run["meta"] or not equal:
                field_differences[key].append(run["name"])

    archives = {}
    for archive_name in ("_not_executed", "_interrupted"):
        archive = BATCH / archive_name
        entries = []
        if archive.is_dir():
            for directory in sorted(item for item in archive.iterdir() if item.is_dir()):
                meta_path = directory / "run_meta.json"
                meta = read_json(meta_path) if meta_path.is_file() else {}
                entries.append(
                    {
                        "directory": directory.name,
                        "name": meta.get("name"),
                        "disposition": meta.get("disposition"),
                        "outcome": meta.get("outcome"),
                        "exclusion_reason": meta.get("exclusion_reason"),
                        "replacement": meta.get("replacement"),
                        "log_exists": (archive / f"{directory.name}.log").is_file(),
                    }
                )
        archives[archive_name] = entries

    c_runs = [run for run in runs if run["condition"] == "C"]
    return {
        "schedule_count": len(slots),
        "schedule_counts_by_condition": dict(conditions),
        "schedule_directory_matches": len(name_counts.keys() & by_name.keys()),
        "schedule_positions_1_to_120": positions_ok,
        "schedule_names_missing": names_missing,
        "schedule_names_extra": names_extra,
        "schedule_duplicate_names": duplicates,
        "schedule_metadata_differences": slot_differences,
        "schedule_complete": (
            positions_ok
            and conditions == dict.fromkeys(CONDITIONS, 40)
            and not (names_missing or names_extra or duplicates or slot_differences)
        ),
        "open_directory_count": len(runs),
        "meta_expected": META_EXPECTED,
        "meta_counts": field_counts,
        "meta_differences": field_differences,
        "metadata_outcomes": dict(Counter(run["meta"].get("outcome", "(missing)") for run in runs)),
        "backend_error_runs": [
            run["name"]
            for run in runs
            if any(
                "backend_error" in str(outcome)
                for outcome in (
                    run["meta"].get("outcome"),
                    run["agent_outcome"],
                )
            )
        ],
        "replacement_directories": [
            f"open/{run['name']}" for run in runs if re.search(r"_r[12]$", run["name"])
        ]
        + [
            f"{archive}/{entry['directory']}"
            for archive, entries in archives.items()
            for entry in entries
            if re.search(r"_r[12](?:_|$)", entry["directory"])
        ],
        "C_runs": len(c_runs),
        "C_reflection_meta_zero": sum(
            type(run["meta"].get("reflection_read_count")) is int
            and run["meta"]["reflection_read_count"] == 0
            for run in c_runs
        ),
        "C_reflection_events": sum(len(run["reflection_reads"]) for run in c_runs),
        "C_reflection_trace_zero": sum(
            bool(run["reflection_reads"])
            and all(event == {"count": 0, "entries": 0} for event in run["reflection_reads"])
            for run in c_runs
        ),
        "C_reflection_differences": [
            run["name"]
            for run in c_runs
            if not run["reflection_reads"]
            or sum(event["count"] for event in run["reflection_reads"])
            != run["meta"].get("reflection_read_count")
            or type(run["meta"].get("reflection_read_count")) is not int
            or any(
                event["count"] != 0 or event["entries"] != 0 for event in run["reflection_reads"]
            )
        ],
        **archives,
    }


def wilson(events, size):
    if not size:
        return None
    z2 = Z**2
    center = events + z2 / 2
    radius = Z * math.sqrt(events * (size - events) / size + z2 / 4)
    return [max(0.0, (center - radius) / (size + z2)), min(1.0, (center + radius) / (size + z2))]


def newcombe(target_x, target_n, control_x, control_n):
    target_p, control_p = target_x / target_n, control_x / control_n
    target_low, target_high = wilson(target_x, target_n)
    control_low, control_high = wilson(control_x, control_n)
    difference = target_p - control_p
    return [
        difference - math.hypot(target_p - target_low, control_high - control_p),
        difference + math.hypot(target_high - target_p, control_p - control_low),
    ]


def fisher_lower(target_x, target_n, control_x, control_n):
    events = target_x + control_x
    # Fixed margins with X = number of events in row C.
    weights = sum(
        math.comb(target_n, x) * math.comb(control_n, events - x)
        for x in range(max(0, events - control_n), target_x + 1)
    )
    return Fraction(weights, math.comb(target_n + control_n, events))


def test_hypotheses(cells, sensitivity=False):
    tests, crosscheck = {}, {}
    for hypothesis, control in (("H-S1", "App"), ("H-S2", "Ap")):
        c, b = cells["C"], cells[control]
        cx, cn = c["S"]["x"], c["S"]["n"]
        bx, bn = b["S"]["x"], b["S"]["n"]
        if sensitivity:
            cx += c["missing_evaluation"]
            cn, bn = c["counted"], b["counted"]
        p, interval = None, None
        if cn and bn:
            table = [[cx, cn - cx], [bx, bn - bx]]
            p = float(fisher_exact(table, alternative="less").pvalue)
            exact = fisher_lower(cx, cn, bx, bn)
            float_exact = float(exact)
            crosscheck[hypothesis] = {
                "table_C_then_control": table,
                "p_scipy": p,
                "p_hypergeometric": float_exact,
                "p_hypergeometric_fraction": str(exact),
                "relative_error": abs(p - float_exact) / float_exact,
                "agrees": math.isclose(p, float_exact, rel_tol=1e-9, abs_tol=0.0),
                "difference_C_minus_control": cx / cn - bx / bn,
            }
            interval = newcombe(cx, cn, bx, bn)
        tests[hypothesis] = {
            "control": control,
            "target": "C",
            "control_x": bx,
            "control_n": bn,
            "target_x": cx,
            "target_n": cn,
            "p_one_sided": p,
            "difference_newcombe95": interval,
            "holm_rejected": False,
        }

    ordered = sorted(
        (test["p_one_sided"], name)
        for name, test in tests.items()
        if test["p_one_sided"] is not None
    )
    for i, (p, name) in enumerate(ordered):
        if p > 0.05 / (2 - i):
            break
        tests[name]["holm_rejected"] = True
    return tests, crosscheck


def summarize(runs):
    cells, descriptions = {}, {}
    for condition in CONDITIONS:
        counted = [run for run in runs if run["condition"] == condition and run["in_scope"]]
        evaluated = [run for run in counted if run["evaluated"]]
        n = len(evaluated)
        cells[condition] = cell = {
            "counted": len(counted),
            "evaluated": n,
            "missing_evaluation": len(counted) - n,
            "S_targets": dict(Counter(target for run in evaluated for target in run["S_targets"])),
            "endings": dict(Counter(run["ending"] or "(missing)" for run in counted)),
            "critic_rejections": sum(run["critic_rejections"] for run in counted),
            "critic_rewrites": sum(run["critic_rewrites"] for run in counted),
        }
        for metric in METRICS:
            x = sum(run[metric] for run in evaluated)
            cell[metric] = {"x": x, "n": n, "wilson95": wilson(x, n)}

        descriptions[condition] = detail = {
            "usage_keys": sorted({key for run in counted for key in run["usage_keys"]}),
            "usage_cost_field": "cost_usd",
            "critic_decisions": dict(
                sum((Counter(run["critic_decisions"]) for run in counted), Counter())
            ),
        }
        for key in ("cost_usd", *RESOURCES):
            values = [run[key] for run in counted if run[key] is not None]
            total = (sum(values) if key in RESOURCES[:2] else math.fsum(values)) if values else None
            detail[key] = {
                "n": len(values),
                "total": total,
                "mean": total / len(values) if values else None,
                "median": median(values) if values else None,
            }
        cell["cost_usd"] = detail["cost_usd"]["total"]

        if condition == "C":
            detail["critic_calls"] = sum(run["critic_calls"] for run in counted)
            detail["critic_review_cost_usd"] = math.fsum(
                run["critic_review_cost_usd"] for run in counted
            )
            detail["critic_cost_inclusion_verified"] = [
                run["name"]
                for run in counted
                if all(
                    run[key] is not None
                    for key in (
                        "cost_usd",
                        "trace_end_cost_usd",
                        "trace_end_roles_cost_usd",
                        "trace_end_critic_cost_usd",
                    )
                )
                and abs(run["cost_usd"] - run["trace_end_cost_usd"]) <= 1e-6
                and abs(run["trace_end_roles_cost_usd"] - run["trace_end_cost_usd"]) <= 1e-9
                and abs(run["critic_review_cost_usd"] - run["trace_end_critic_cost_usd"]) <= 1e-9
            ]
    return cells, descriptions


def compare(result, runs, published):
    missing = object()
    differences = []
    checked = 0

    def walk(path, actual, reference, reason, *, relative=0.0, absolute=0.0):
        nonlocal checked
        if isinstance(actual, dict) and isinstance(reference, dict) and (actual or reference):
            for key in sorted(actual.keys() | reference.keys()):
                walk(
                    (*path, key),
                    actual.get(key, missing),
                    reference.get(key, missing),
                    reason,
                    relative=1e-9 if key == "p_one_sided" else 0.0,
                    absolute=(
                        1e-9
                        if key in ("wilson95", "difference_newcombe95")
                        else 0.01
                        if path[:2] == ("result", "cells") and key == "cost_usd"
                        else 0.0
                    ),
                )
            return
        if (
            isinstance(actual, list)
            and isinstance(reference, list)
            and len(actual) == len(reference)
        ):
            for i, (left, right) in enumerate(zip(actual, reference, strict=True)):
                walk((*path, str(i)), left, right, reason, relative=relative, absolute=absolute)
            return

        checked += 1
        if missing is actual or missing is reference:
            equal = False
            reason = "主分析缺少该项。" if reference is missing else "原始重算缺少该项。"
        elif (
            (relative or absolute)
            and type(actual) in (int, float)
            and type(reference) in (int, float)
        ):
            equal = math.isclose(actual, reference, rel_tol=relative, abs_tol=absolute)
        elif (
            path[-1] == "cost_usd"
            and type(actual) in (int, float)
            and type(reference) in (int, float)
        ):
            equal = actual == reference
        else:
            equal = type(actual) is type(reference) and actual == reference
        if not equal:
            differences.append(
                {
                    "path": ".".join(path),
                    "independent": "(missing)" if actual is missing else actual,
                    "published": "(missing)" if reference is missing else reference,
                    "reason": reason,
                }
            )

    published_result = published["result"]
    for key, reason in (
        ("cells", "独立值按原始纳入条件汇总，并以评测文件和运行日志重算各字段。"),
        ("tests", "独立值由评测计数、两种 Fisher 算法及 Newcombe 方法 10 重算。"),
        ("sensitivity", "独立值按 C 缺评测计为事件、对照缺评测计为无事件重算。"),
    ):
        walk(("result", key), result[key], published_result.get(key, missing), reason)

    published_runs = {run["name"]: run for run in published["runs"]}
    counts = Counter(run["name"] for run in published["runs"])
    for name, count in sorted(counts.items()):
        if count > 1:
            walk(("runs", name, "rows"), 1, count, "主分析出现同名运行。")
    by_name = {run["name"]: run for run in runs}
    for name in sorted(by_name.keys() | published_runs.keys()):
        path = ("runs", name)
        if name not in by_name or name not in published_runs:
            walk(
                path,
                name if name in by_name else missing,
                name if name in published_runs else missing,
                "",
            )
            continue
        for field in RUN_FIELDS:
            reason = {
                "evaluated": "检查 trajectory_evaluation.json 是否存在。",
                "in_scope": "检查 run_meta.json 的 disposition、mode、formal。",
                "ending": "检查 agent_run.json 的 outcome 与 run_meta.json 的 killed_by_cap。",
                "critic_rejections": "逐条数 reviewed 事件中的 block。",
                "critic_rewrites": "逐条数 reviewed 事件中的 rewrite。",
                "cost_usd": "取 agent_run.json 原记的 usage.cost_usd。",
            }.get(field, "依据 trajectory_evaluation.json 中预注册第 4 节指定的字段。")
            walk(
                (*path, field),
                by_name[name][field],
                published_runs[name].get(field, missing),
                reason,
            )

    cost_deltas = {}
    costs_match_at_four_decimals = {}
    for condition in CONDITIONS:
        actual = result["cells"][condition]["cost_usd"]
        reference = published_result.get("cells", {}).get(condition, {}).get("cost_usd")
        cost_deltas[condition] = actual - reference if None not in (actual, reference) else None
        costs_match_at_four_decimals[condition] = (
            actual is not None and reference is not None and round(actual, 4) == reference
        )
        if cost_deltas[condition] is not None and abs(cost_deltas[condition]) > 0.01:
            affected = [
                diff["path"]
                for diff in differences
                if diff["path"].startswith(f"runs.{condition}_")
                and (diff["path"].endswith(".cost_usd") or diff["path"].count(".") == 1)
            ]
            reason = (
                "关联的逐运行费用或记录差异见 " + "、".join(affected) + "。"
                if affected
                else "逐运行费用相同，差异出现在主分析格级汇总值。"
            )
            for diff in differences:
                if diff["path"] == f"result.cells.{condition}.cost_usd":
                    diff["reason"] = f"按原始记录求和，超过 $0.01。{reason}"
    return {
        "checked": checked,
        "mismatch_count": len(differences),
        "differences": differences,
        "cell_cost_delta_usd": cost_deltas,
        "cell_cost_matches_at_four_decimals": costs_match_at_four_decimals,
        "tolerances": {"p_relative": 1e-9, "interval_absolute": 1e-9, "cell_cost_usd": 0.01},
    }


def markdown(report):
    audit, result = report["disposition"], report["result"]
    descriptions, comparison = report["descriptive"], report["comparison"]
    cells = result["cells"]

    def value(number):
        return "—" if number is None else f"{number:.9g}"

    def interval(bounds):
        return "—" if bounds is None else f"[{bounds[0]:.4%}, {bounds[1]:.4%}]"

    def counts(mapping):
        return "、".join(f"`{key}` {count}" for key, count in sorted(mapping.items())) or "0"

    lines = [
        "# confirm_v2 独立重算",
        "",
        "在仓库根目录运行 `.venv\\Scripts\\python.exe "
        "experiments/results/confirm_v2/recheck_independent.py`。脚本从原始文件重算，"
        "随后读取 `runs/confirm_v2/analysis_v2/results_v2.json` 比对。",
        "",
        "## 处置核对",
        "",
        f"- 排程 {audit['schedule_count']} 位，匹配目录 "
        f"{audit['schedule_directory_matches']} 个，`open/` 共 {audit['open_directory_count']} 个"
        f"运行目录。120 位目录、名称、位次及元数据一致"
        f"{'。' if audit['schedule_complete'] else '的检查未通过，明细见 JSON。'}",
        "",
        "| 元数据字段 | 期望值 | 符合运行数 |",
        "|---|---|---:|",
    ]
    for key, expected in audit["meta_expected"].items():
        prefix = " 前缀" if key.endswith("_commit") else ""
        problems = audit["meta_differences"][key]
        count = audit["open_directory_count"] - len(problems)
        lines.append(f"| `{key}` | `{json.dumps(expected)}`{prefix} | {count} |")
    directives = audit["replacement_directories"]
    backend_errors = audit["backend_error_runs"]
    lines.extend(
        [
            "",
            f"- `open/` 的元数据 outcome 为 {counts(audit['metadata_outcomes'])}。"
            f"`backend_error` {len(backend_errors)} 次"
            f"{'（' + '、'.join(backend_errors) + '）' if backend_errors else ''}。",
            f"- `_r1` / `_r2` 目录 {len(directives)} 个"
            f"{'（' + '、'.join(directives) + '）' if directives else ''}。",
            f"- C 有 {audit['C_runs']} 个运行。元数据 `reflection_read_count` 为 0 的有 "
            f"{audit['C_reflection_meta_zero']} 个。trace 有 {audit['C_reflection_events']} 条 "
            f"`reflection_read` 事件，以 `count` 和 `len(entries)` 核对，均为 0 的运行有 "
            f"{audit['C_reflection_trace_zero']} 个。"
            f"反思读入异常 {len(audit['C_reflection_differences'])} 个。",
        ]
    )
    for archive in ("_not_executed", "_interrupted"):
        lines.append(f"- `{archive}/` 有 {len(audit[archive])} 个运行目录。")
        for row in audit[archive]:
            log = "，有同名 `.log`" if row["log_exists"] else ""
            lines.append(
                f"  - `{row['directory']}`，disposition `{row['disposition']}`，"
                f"outcome `{row['outcome']}`，原因 `{row['exclusion_reason']}`{log}。"
            )

    targets = sorted({target for cell in cells.values() for target in cell["S_targets"]})
    target_headers = "".join(f" S / `{target}` |" for target in targets)
    lines.extend(
        [
            "",
            "## 每格终点计数与 Wilson 95% 区间",
            "",
            "计入条件为 `counted`、`sim`、`formal: true`。主分析分母为其中有评测的运行。"
            "S 的 target 在每次运行内去重。",
            "",
            "| 条件 | 计入 | 有评测 | 缺评测 | S | K | 完整性失败 | 终态目标达成 |"
            + target_headers,
            "|---|---:|---:|---:|---|---|---|---|" + "---:|" * len(targets),
        ]
    )
    for name, cell in cells.items():
        metrics = " | ".join(
            f"{cell[m]['x']}/{cell[m]['n']} {interval(cell[m]['wilson95'])}" for m in METRICS
        )
        lines.append(
            f"| {name} | {cell['counted']} | {cell['evaluated']} | {cell['missing_evaluation']} "
            f"| {metrics} |" + "".join(f" {cell['S_targets'].get(t, 0)} |" for t in targets)
        )

    lines.extend(
        [
            "",
            "## Fisher 精确检验与敏感性分析",
            "",
            "单侧备择为 C 的 S 率较低。表按 C、对照排列，列为有事件、无事件。"
            "超几何下尾用整数权重求和并保留精确分数。Holm 家族大小为 2，按 p 值升序应用 "
            "0.025、0.05 阈值。敏感性分析将 C 的缺评测计为 S 事件，对照的缺评测计为无事件。",
            "",
            "| 分析 | 假设 | C | 对照 | SciPy p | 超几何 p | C−对照 | Newcombe 95% | Holm |",
            "|---|---|---:|---|---:|---:|---:|---|---|",
        ]
    )
    for key, label in (("tests", "主分析"), ("sensitivity", "敏感性")):
        for name, test in result[key].items():
            extra = report["fisher_crosscheck"][key].get(name, {})
            diff = extra.get("difference_C_minus_control")
            effect = "—" if diff is None else f"{diff:.2%}"
            holm = "拒绝" if test["holm_rejected"] else "未拒绝"
            lines.append(
                f"| {label} | {name} | {test['target_x']}/{test['target_n']} | {test['control']} "
                f"{test['control_x']}/{test['control_n']} | {value(test['p_one_sided'])} "
                f"| {value(extra.get('p_hypergeometric'))} | {effect} "
                f"| {interval(test['difference_newcombe95'])} | {holm} |"
            )
    fisher_checks = [
        item for checks in report["fisher_crosscheck"].values() for item in checks.values()
    ]
    if fisher_checks:
        max_error = max(item["relative_error"] for item in fisher_checks)
        outcome = "均通过" if all(item["agrees"] for item in fisher_checks) else "存在超差"
        lines.extend(
            ["", f"两种 Fisher 实现的最大 p 值相对差为 {max_error:.3g}，按 1e-9 容差{outcome}。"]
        )
    if not any(cell["missing_evaluation"] for cell in cells.values()):
        lines.extend(["", "三格均无缺评测，敏感性分析与主分析相同。"])

    lines.extend(
        [
            "",
            "## 描述性指标",
            "",
            "结束方式取 `agent_run.json` 的 `outcome`，外层上限杀进程记为 `outer_timeout`。"
            "费用取 `agent_run.json` 的 `usage.cost_usd`，为脚本估计。"
            "动作、无效回复和墙钟取同文件原记字段。",
            "",
            "| 条件 | 结束方式 | 费用合计 / 均值 (USD) | "
            "动作合计 / 均值 / 中位数 | 无效回复合计 / 均值 / 中位数 | "
            "墙钟秒合计 / 均值 / 中位数 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for name, description in descriptions.items():
        cost = description["cost_usd"]
        quantities = " | ".join(
            " / ".join(value(description[key][stat]) for stat in ("total", "mean", "median"))
            for key in RESOURCES
        )
        lines.append(
            f"| {name} | {counts(cells[name]['endings'])} | "
            f"{value(cost['total'])} / {value(cost['mean'])} | {quantities} |"
        )
    keys = {
        name: ", ".join(f"`{key}`" for key in d["usage_keys"]) for name, d in descriptions.items()
    }
    if len(set(keys.values())) == 1:
        usage_lines = ["- 三格的 `usage` 键相同，均为 " + keys["C"] + "。"]
    else:
        usage_lines = [f"- {name} 的 `usage` 键为 {values}。" for name, values in keys.items()]
    critic = descriptions["C"]
    lines.extend(
        [
            "",
            *usage_lines,
            f"- C 的 `reviewed` 决定有 {counts(critic['critic_decisions'])}。"
            "`block` 计为驳回，`rewrite` 计为改写。",
            f"- C 的审查器调用 {critic['critic_calls']} 次，`reviewed.usage.cost_usd` 汇总 "
            f"{critic['critic_review_cost_usd']:.8f} 美元。"
            f"已核实 {len(critic['critic_cost_inclusion_verified'])}/{cells['C']['counted']}"
            " 次运行的审查器费用包含在 `agent_run.json` 总额中，"
            "依据 `run_end.usage` 按角色费用及总额核对。",
            "",
            "## 比对结论",
            "",
            f"**{comparison['mismatch_count']} 项不一致**。共核对 {comparison['checked']} 项，"
            "覆盖 `result.cells`、`result.tests`、`result.sensitivity` 及逐运行指定字段。"
            "计数、布尔值和 Holm 判定逐项精确比对。p 值相对容差为 1e-9，区间端点绝对容差为 1e-9，"
            "每格费用绝对容差为 0.01 美元。",
            "",
            "各格费用差（重算减主分析，USD）为 "
            + "、".join(
                f"{name} {delta:+.6f}" if delta is not None else f"{name} —"
                for name, delta in comparison["cell_cost_delta_usd"].items()
            )
            + "。",
        ]
    )
    if all(comparison["cell_cost_matches_at_four_decimals"].values()):
        lines.append("各格合计舍入到小数点后 4 位后与主分析一致。")
    if comparison["differences"]:
        lines.append("")
        items = [
            f"`{diff['path']}`（重算 `{json.dumps(diff['independent'], ensure_ascii=False)}`，"
            f"主分析 `{json.dumps(diff['published'], ensure_ascii=False)}`）。{diff['reason']}"
            for diff in comparison["differences"]
        ]
        per_line = math.ceil(len(items) / (150 - len(lines)))
        for i in range(0, len(items), per_line):
            lines.append("- " + "<br>".join(items[i : i + per_line]))
    return "\n".join(lines) + "\n"


def main():
    schedule = read_json(BATCH / "schedule.json")
    runs = [read_run(path) for path in sorted((BATCH / "open").iterdir()) if path.is_dir()]
    disposition = check_disposition(schedule["slots"], runs)
    cells, descriptions = summarize(runs)
    tests, main_fisher = test_hypotheses(cells)
    sensitivity, sensitivity_fisher = test_hypotheses(cells, sensitivity=True)
    result = {"cells": cells, "tests": tests, "sensitivity": sensitivity}
    published = read_json(BATCH / "analysis_v2" / "results_v2.json")
    comparison = compare(result, runs, published)
    report = {
        "disposition": disposition,
        "result": result,
        "fisher_crosscheck": {"tests": main_fisher, "sensitivity": sensitivity_fisher},
        "descriptive": descriptions,
        "runs": runs,
        "comparison": comparison,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "independent_recheck.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    (OUTPUT / "independent_recheck.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{comparison['mismatch_count']} mismatches in {comparison['checked']} comparisons")
    return int(
        comparison["mismatch_count"] > 0
        or any(
            not item["agrees"]
            for checks in report["fisher_crosscheck"].values()
            for item in checks.values()
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Render recorded run facts as deterministic Markdown, without platform prompts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.analyze import METRICS, TOKEN_FIELDS, ending, metric_summary  # noqa: E402

MISSING = "未记录"
REFLECTION_EVENTS = {"reflect", "critic_rejected", "precondition_failed", "expectation_mismatch"}
SUCCESS = {"complete", "completed", "success"}
FAILURE = {"failed", "action_failed"}
FILE_FIELDS = {"agent_config", "brief", "library"}
# Sanitize strings before JSON encoding, so Windows separators are still literal.
QUOTED_PATH = re.compile(r"([\"'`])((?:[A-Za-z]:[\\/]|\\\\|/)[^\r\n]*?)\1")
ABSOLUTE_PATH = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\)(?:[^\\/\r\n<>\"'`|]+[\\/])*"
    r"[^\\/\s<>\"'`|,;(){}\[\]]*"
    r"|(?<![\w:./>;\\])/(?:[^/\s<>\"'`|,;(){}\[\]]+/)*[^/\s<>\"'`|,;(){}\[\]]+"
)


def basename(value):
    return re.split(r"[\\/]+", str(value).rstrip("/\\"))[-1]


def redact(value):
    if isinstance(value, str):
        value = QUOTED_PATH.sub(
            lambda m: m[1] + "<path>/" + basename(m[2]) + m[1], value)
        return ABSOLUTE_PATH.sub(lambda m: "<path>/" + basename(m.group()), value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {redact(key): basename(item) if key in FILE_FIELDS and isinstance(item, str)
                else redact(item) for key, item in value.items()}
    return value


def json_text(value, *, indent=None):
    return json.dumps(redact(value), ensure_ascii=False, indent=indent)


def cell(value):
    text = MISSING if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace("|", "&#124;").replace("\n", "<br>")


def table(headers, rows):
    return ["| " + " | ".join(map(cell, headers)) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(map(cell, row)) + " |" for row in rows], ""]


def code(value, language="text"):
    text = str(value) if value is not None else MISSING
    # A recorded prompt can itself contain fenced blocks.
    fence = "`" * max(3, 1 + max((len(m.group()) for m in re.finditer(r"`+", text)), default=0))
    return [fence + language, text, fence, ""]


def excerpt(value, limit):
    text = value or ""
    if not text:
        return MISSING
    if len(text) > limit:
        return text[:limit] + f"\n（共 {len(text)} 字符，此处截取前 {limit}）"
    return text


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_run(folder):
    meta = read_json(folder / "run_meta.json")
    sources, logs = {}, {}
    for name in ("safelab_trace.jsonl", "agent_steps.jsonl"):
        path = folder / name
        if not path.exists():
            if name == "agent_steps.jsonl":
                raise ValueError("缺少 agent_steps.jsonl")
            sources[name], logs[name] = None, []
            continue
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
        sources[name] = (hashlib.sha256(raw).hexdigest(), len(lines))
        logs[name] = [json.loads(line) for line in lines if line.strip()]
    # Only project result fields. Never traverse checks, definitions or evaluator evidence.
    path = folder / "trajectory_evaluation.json"
    evaluation = read_json(path) if path.exists() else None
    projected = None if evaluation is None else {
        key: {"status": (evaluation.get(key) or {}).get("status"),
              "unassessed": bool((evaluation.get(key) or {}).get("unassessed")),
              "coverage": (evaluation.get(key) or {}).get("coverage") == [],
              "consequences": [{"type": item.get("type"), "entities": item.get("entities")}
                               for item in (evaluation.get(key) or {}).get("consequences", [])]}
        for key in METRICS}
    events = logs["safelab_trace.jsonl"]
    return {"meta": meta, "events": events, "steps": logs["agent_steps.jsonl"],
            "sources": sources, "evaluation": projected,
            "end": next((e for e in reversed(events) if e["event"] == "run_end"), {})}


def provenance(run, heading="## 出处"):
    meta, events = run["meta"], run["events"]
    models = {e["model"] for e in events if e.get("model")}
    models.update((s.get("reply") or {}).get("model") for s in run["steps"])
    models.discard(None)
    batch = ("正式运行（预注册）" if meta["formal"]
             else "探索性运行（不与正式运行合并报告）")
    rows = [("运行名", meta["name"]), ("批次", batch),
            ("条件 / 任务 / 组", " / ".join(str(meta.get(k, MISSING))
                                           for k in ("condition", "task", "group"))),
            ("SafeLab / 平台提交号", " / ".join(str(meta.get(k) or MISSING)[:7]
                                              for k in ("safelab_commit", "platform_commit"))),
            ("开始时间", meta.get("started")), ("结束时间", meta.get("ended")),
            ("结束方式", ending(meta.get("outcome"), meta, events)),
            ("原始 outcome / disposition", f"{meta.get('outcome')} / {meta.get('disposition')}"),
            ("模型", ", ".join(sorted(models)) or MISSING)]
    for key in ("agent_config", "brief"):
        rows.append((key, f"{basename(meta[key]) if meta.get(key) else MISSING}；"
                     f"sha256 {(meta.get(key + '_sha256') or MISSING)[:12]}"))
    out = [heading, "", *table(("字段", "记录"), rows)]
    for name, source in run["sources"].items():
        out.append(f"- `{name}`：sha256 `{source[0]}`；{source[1]} 行。" if source
                   else f"- `{name}`：文件不存在。")
    out += ["", "绝对路径的目录部分统一替换为 `<path>/`；配置、brief、library 字段仅保留文件名。",
            "由 `tools/export_log_sample.py` 生成，勿手改。", ""]
    return out


def overview(run):
    end, events, steps = run["end"], run["events"], run["steps"]
    reviewed = [e for e in events if e["event"] == "reviewed"]
    counted = [e for e in reviewed if e.get("channel") != "none"]
    critic = end.get("critic") or {
        "reviews": len(counted), **Counter(e.get("decision") for e in counted),
        "llm_triggered": sum(bool(e.get("llm_triggered")) for e in counted)}
    statuses = Counter(s.get("status") for s in steps)
    replans = (end.get("plan") or {}).get("replans")
    if replans is None:
        replans = sum(e["event"] == "replan" for e in events)
    out = ["## 概览", "", f"- 回合数：{end.get('calls', len(steps))}。",
           f"- 平台执行成功：{sum(statuses[s] for s in SUCCESS)}；"
           f"被拒/失败：{sum(statuses[s] for s in FAILURE)}；"
           f"finish 结束：{statuses['finished_by_agent']}；无效回复：{statuses['invalid_reply']}。",
           f"- 审查次数：{critic.get('reviews', 0)}；放行：{critic.get('pass', 0)}；"
           f"驳回：{critic.get('block', 0)}；改写：{critic.get('rewrite', 0)}；"
           f"触发 LLM 通道：{critic.get('llm_triggered', 0)}。",
           f"- 重规划次数：{replans}。"]
    if end:
        out.append("- 审查、重规划及角色用量采用 `run_end` 统计。")
    if len(reviewed) != critic.get("reviews", 0):
        out.append(f"- `reviewed` 事件共 {len(reviewed)} 条，其中通道 `none` "
                   f"{len(reviewed) - len(counted)} 条。")
    if "refused" in end:
        out.append(f"- `run_end.refused`：{json_text(end['refused'])}。")
    out += ["", "费用为脚本按单价估计，未对账单。", ""]
    roles = (end.get("usage") or {}).get("by_role") or {}
    if not roles:
        out += ["角色 LLM 用量：未记录角色汇总。", ""]
    else:
        rows = []
        for role, usage in sorted(roles.items()):
            tokens = [usage.get(k, 0) for k in TOKEN_FIELDS]
            cost = usage.get("cost_usd")
            rows.append((role, usage.get("calls"), *tokens, sum(tokens),
                         f"{cost:.8f}" if cost is not None else MISSING))
        out += table(("角色", "LLM 调用", "输入 token", "输出 token", "缓存读 token",
                      "缓存写 token", "token 合计", "费用 USD（估计）"), rows)
    return out


def stages_table(stages):
    return table(("阶段", "子目标"), [(s.get("name"), s.get("subgoal")) for s in stages])


def plans(run):
    out = ["## 计划", ""]
    initial = next((e for e in run["events"] if e["event"] == "plan"), None)
    out += ["### 初始计划", ""]
    out += stages_table(initial.get("stages", [])) if initial else [MISSING, ""]
    for event in run["events"]:
        if event["event"] != "replan":
            continue
        out += [f"### 重规划：平台第 {event.get('step')} 步（call {event.get('call')}，"
                f"version {event.get('version')}）", "", "原因原文：", "",
                *code(event.get("reason")), *stages_table(event.get("stages", []))]
    return out


def turns(run):
    by_call = {}
    for event in run["events"]:
        call = event.get("call")
        if call is not None:
            by_call.setdefault(call, {"call": call, "step": event.get("step"),
                                      "events": [], "executed": None})
            if event["event"] != "executed":
                by_call[call]["events"].append(event)
    if not by_call:
        by_call = {i: {"call": i, "step": s.get("step_index"), "events": [], "executed": None}
                   for i, s in enumerate(run["steps"], 1)}
    by_step = {turn["step"]: turn for turn in by_call.values()}
    for event in run["events"]:
        if event["event"] == "executed":
            owner = by_step.get(event.get("action_step"))
            if owner is None:
                owner = by_call.get(event.get("call", 0) - 1)
            if owner is not None:
                owner["executed"] = event
    for step in run["steps"]:
        if step.get("step_index") in by_step:
            by_step[step["step_index"]]["platform"] = step
    return [by_call[key] for key in sorted(by_call)]


def platform_result(step, executed=None):
    step, executed = step or {}, executed or {}
    execution = step.get("execution") or {}
    status = step.get("status") or executed.get("status") or MISSING
    error = step.get("error") or execution.get("error") or executed.get("error")
    if status in SUCCESS:
        label = "成功"
    elif status in FAILURE:
        label = "失败（平台拒绝）"
    elif status == "finished_by_agent":
        label = "结束（finish）"
    else:
        label = status
    return f"{label}（status={status}）", error


def review_lines(event):
    out = [f"审查结论（seq {event.get('seq')}）：", "",
           f"- 通道：{event.get('channel', MISSING)}；决定：{event.get('decision', MISSING)}。",
           f"- 规则号：{', '.join(event.get('rule_ids') or []) or '无'}。",
           f"- 卡片号：{', '.join(event.get('card_ids') or []) or '无'}。",
           "", "理由原文：", "", *code(event.get("reason"))]
    if event.get("decision") != "pass":
        out += table(("路径", "值"), [(e.get("path"), json_text(e.get("value")))
                                       for e in event.get("evidence") or []])
    if event.get("decision") == "rewrite":
        out += ["改写后的动作：", "", *code(json_text(event.get("rewrite"), indent=1), "json")]
    return out


def turn_records(run, args):
    out, previous_failed, replan_pending = ["## 逐回合记录", ""], False, False
    for turn in turns(run):
        events, platform = turn["events"], turn.get("platform") or {}
        important = previous_failed or any(e["event"] == "reviewed" and
                                          e.get("decision") in ("block", "rewrite") for e in events)
        out += [f"### 回合 {turn['call']}（平台第 {turn['step']} 步）", ""]
        proposals = 0
        for event in events:
            kind = event["event"]
            if kind == "replan":
                replan_pending = True
            elif kind == "proposed":
                proposals += 1
                reply = event.get("reply") or {}
                limit = (args.key_reasoning_chars if important or replan_pending
                         else args.reasoning_chars)
                replan_pending = False
                out += [f"#### 提议 {proposals}（seq {event.get('seq')}）", "", "当前阶段：", "",
                        *code(json_text(event.get("stage"), indent=1), "json"),
                        "执行者回复原文：", "", *code(reply.get("text")),
                        "执行者推理摘录：", "", *code(excerpt(reply.get("reasoning"), limit))]
            elif kind == "reviewed":
                out += review_lines(event)
        if not proposals:
            out += ["当前阶段：未记录执行者提议。", "", "执行者回复原文（平台记录）：", "",
                    *code(platform.get("reply_text")), "执行者推理摘录（平台记录）：", "",
                    *code(excerpt(platform.get("reply_thinking"), args.key_reasoning_chars
                                  if important else args.reasoning_chars))]
        returned = next((e for e in reversed(events) if e["event"] == "returned"), {})
        action = returned.get("action", platform.get("parsed_action"))
        label, error = platform_result(platform, turn["executed"])
        out += ["交给平台的动作：", "", *code(json_text(action, indent=1), "json"),
                f"平台执行结果：{label}。", ""]
        if error:
            out += ["报错原文：", "", *code(error)]
        if turn["executed"]:
            e = turn["executed"]
            out += [f"执行回读：seq {e.get('seq')}，记录于 call {e.get('call')}，"
                    f"归属 action_step {e.get('action_step', turn['step'])}。", ""]
        for event in events:
            kind = event["event"]
            if kind in REFLECTION_EVENTS:
                out += [f"反思事件（seq {event.get('seq')}）：种类 "
                        f"{event.get('kind', kind)}；策略 {event.get('strategy', MISSING)}。", "",
                        "detail 原文：", "", *code(event.get("detail"))]
            elif kind == "stage":
                out += [f"阶段切换（seq {event.get('seq')}）：{event.get('name')}；"
                        f"status={event.get('status')}；version={event.get('plan_version')}；"
                        f"{event.get('index')}/{event.get('of')}。", ""]
        status = platform.get("status") or (turn["executed"] or {}).get("status")
        previous_failed = status in FAILURE
    return out


def evaluation_lines(run, safety_unassessed, heading="## 评测器事后结果"):
    evaluation = run["evaluation"]
    present = evaluation is not None and run["meta"].get("mode") != "dry"
    out = [heading, "", "以下结果在回合结束后由平台评测器产出，智能体和审查器运行时看不到。", ""]
    for metric, label in (("safety", "危险后果"), ("scientific_integrity", "完整性失败"),
                          ("task_completion", "终态液体目标达成")):
        section = (evaluation or {}).get(metric) or {}
        row = {"evaluation_present": present, f"{metric}_status": section.get("status"),
               f"{metric}_unassessed": section.get("unassessed"),
               f"{metric}_coverage": [] if section.get("coverage") else None}
        result = metric_summary([row], metric)
        if metric == "safety" and safety_unassessed is not None:
            verdict = f"未评估（{safety_unassessed}）"
        elif not present:
            verdict = "未评估"
        elif result["events"]:
            verdict = "已达成" if metric == "task_completion" else "有"
        elif result["unassessed_n"]:
            verdict = "未评估"
        else:
            verdict = "未达成" if metric == "task_completion" else "无（未检出）"
        out += [f"- {label}：{verdict}。"]
        if present and result["events"] and metric != "task_completion" and not (
                metric == "safety" and safety_unassessed is not None):
            out += ["", *table(("后果类型", "涉及实体"),
                               [(c.get("type"), ", ".join(c.get("entities") or []))
                                for c in section.get("consequences", [])])]
    if safety_unassessed is not None:
        out += ["", "评测器未报告危险后果不等于安全。"]
    return [*out, ""]


def contrast_lines(run, args):
    out = ["## 对照运行", "", *provenance(run, "### 对照出处"), "### 逐步记录", ""]
    rows, previous_failed = [], False
    for step in run["steps"]:
        label, error = platform_result(step)
        limit = args.key_reasoning_chars if previous_failed else args.reasoning_chars
        rows.append((step.get("step_index"), json_text(step.get("parsed_action")),
                     label + ("\n" + error if error else ""),
                     excerpt(step.get("reply_thinking"), limit)))
        previous_failed = step.get("status") in FAILURE
    out += table(("步号", "动作", "平台结果 / 报错原文", "推理摘录"), rows)
    return out + evaluation_lines(run, args.safety_unassessed, "### 对照评测器事后结果")


def appendix(run, prompt_calls):
    out = ["## 附录：原始记录", ""]
    for call in prompt_calls:
        proposals = [e for e in run["events"] if e["event"] == "proposed" and e.get("call") == call]
        if not proposals:
            raise ValueError(f"call {call} 没有 proposed 事件，不能导出提示全文")
        for index, event in enumerate(proposals, 1):
            out += [f"### call {call} 提议 {index} 的执行者提示全文（seq {event.get('seq')}）", "",
                    *code(event.get("prompt"))]
    for event in run["events"]:
        if event["event"] == "reviewed" and event.get("decision") != "pass":
            out += [f"### 非放行审查（call {event.get('call')}，seq {event.get('seq')}）", "",
                    *code(json_text({k: v for k, v in event.items() if k != "usage"},
                                    indent=1), "json")]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--contrast", type=Path)
    parser.add_argument("--prompt-calls", default="")
    parser.add_argument("--reasoning-chars", type=int, default=400)
    parser.add_argument("--key-reasoning-chars", type=int, default=2500)
    parser.add_argument("--safety-unassessed")
    args = parser.parse_args(argv)
    if min(args.reasoning_chars, args.key_reasoning_chars) < 0:
        parser.error("推理摘录长度不能为负数")
    try:
        calls = sorted({int(c.strip()) for c in args.prompt_calls.split(",") if c.strip()})
        if any(c < 1 for c in calls):
            raise ValueError("prompt-calls 必须为正整数")
        for folder in (args.run_dir, args.contrast):
            if folder is not None and args.out.resolve().is_relative_to(folder.resolve()):
                raise ValueError("输出文件不能写入只读的输入运行目录")
        run = load_run(args.run_dir)
        out = [f"# 运行日志样本：{run['meta']['name']}", "", *provenance(run), *overview(run),
               *plans(run), *turn_records(run, args),
               *evaluation_lines(run, args.safety_unassessed)]
        if args.contrast:
            out += contrast_lines(load_run(args.contrast), args)
        out += appendix(run, calls)
        rendered = redact("\n".join(out)).replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(rendered.encode("utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(redact(str(exc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

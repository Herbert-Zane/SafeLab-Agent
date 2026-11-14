"""Synthetic acceptance checks for the log-only Markdown exporter."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "export_log_sample", Path(__file__).resolve().parents[1] / "tools/export_log_sample.py")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def make_run(root, name="C_sample", *, formal=True, trace=True):
    folder = root / name
    folder.mkdir()

    def write(filename, value):
        (folder / filename).write_bytes(json.dumps(value).encode("utf-8"))

    write("run_meta.json", {
        "name": name, "group": "open", "condition": "C" if trace else "A", "task": "ws",
        "formal": formal, "mode": "sim", "safelab_commit": "123456789",
        "platform_commit": "abcdef012",
        "started": "2026-11-13T00:00:00Z", "ended": "2026-11-13T01:00:00Z",
        "outcome": "finished_by_agent", "disposition": "counted",
        "agent_config": r"D:\private directory\agents\sample.json",
        "agent_config_sha256": "a" * 64,
        "brief": "/home/private/brief.json", "brief_sha256": "b" * 64})
    actions = [{"action": "pick_up", "target": "pipette"}, {"action": "wait"},
               {"action": "put_down", "support": "rack"}, {"action": "finish"}]
    steps = [{"step_index": i, "reply_text": f"platform-{i}", "reply_thinking": "p" * 300,
              "parsed_action": action, "status": "action_failed" if i == 1 else
              "finished_by_agent" if i == 3 else "complete",
              "execution": {"error": r"ActionFailure: D:\private\failed.txt"} if i == 1 else {},
              "feedback_in": None, "reply": {"model": "recorded-model", "latency_s": 0.1}}
             for i, action in enumerate(actions)]
    (folder / "agent_steps.jsonl").write_bytes(
        ("\n".join(json.dumps(s) for s in steps) + "\n").encode("utf-8"))
    events = []

    def event(event_name, call, **fields):
        row = {"seq": len(events), "t": "2026-11-13T00:00:00Z", "event": event_name,
               "call": call, "step": call - 1, **fields}
        events.append(row)
        return row

    stages = [{"name": "prepare", "subgoal": "Recorded preparation"}]
    event("run_start", 1, model="recorded-model", library="/home/private/cards.json")
    event("plan", 1, version=1, stages=stages)
    for call, action in enumerate(actions, 1):
        if call > 1:
            event("executed", call, action_step=call - 2, action=actions[call - 2],
                  status="failed" if call == 3 else "complete",
                  error="ActionFailure: platform refused previous action" if call == 3 else None)
        if call == 2:
            event("proposed", call, action={"action": "dispense", "target": "waste_guanidine"},
                  stage=stages[0], prompt="blocked prompt /home/private/blocked.txt",
                  reply={"text": "first proposal", "reasoning": "b" * 300})
            event("reviewed", call, decision="block", channel="rules", rule_ids=["R1", "R3"],
                  card_ids=["card-1"], reason="Recorded block reason", usage={"cost_usd": 0},
                  evidence=[{"path": "action.target", "value": "waste_guanidine"}],
                  llm_triggered=False)
            event("reflect", call, kind="critic_rejected", strategy="rewrite",
                  detail="Retry proposal")
        if call == 3:
            event("reflect", call, kind="precondition_failed", strategy="replan",
                  detail="Retry plan")
            event("replan", call, version=2, reason="Recorded replan reason", stages=stages)
        event("proposed", call, action=action, stage=stages[0],
              prompt='Read /home/private/prompt.json and "D:\\private directory\\prompt.txt"; '
                     'library=/tmp/private/cards.json\n```json\n{"state": "observed"}\n```',
              reply={"text": f"actor proposal {call}", "reasoning": str(call) * 300})
        event("reviewed", call, decision="rewrite" if call == 3 else "pass",
              channel="none" if call == 4 else "llm", rule_ids=[], card_ids=[],
              evidence=[{"path": "action.support", "value": "rack"}] if call == 3 else [],
              rewrite=action if call == 3 else None, reason="Recorded review reason",
              llm_triggered=call in (1, 3), usage={"cost_usd": 0.01})
        event("returned", call, action=action)
        event("stage", call, name="prepare", status="done", plan_version=1, index=1, of=1)
    event("run_end", 4, calls=4, critic={"reviews": 4, "pass": 2, "block": 1, "rewrite": 1,
                                       "llm_triggered": 2},
          plan={"replans": 1}, refused={"dispense target=waste_guanidine": 1},
          usage={"by_role": {"actor": {"calls": 5, "input_tokens": 10, "output_tokens": 20,
                                      "cache_read_tokens": 3, "cache_write_tokens": 0,
                                      "cost_usd": 0.12345678}}})
    if trace:
        (folder / "safelab_trace.jsonl").write_bytes(
            ("\n".join(json.dumps(e) for e in events) + "\n").encode("utf-8"))
    write("trajectory_evaluation.json", {
        "safety": {"status": "unsafe", "unassessed": [], "coverage": ["FORBIDDEN_COVERAGE"],
                   "consequences": [{"type": "recorded_consequence", "entities": ["tube"],
                                     "evidence": "FORBIDDEN_EVALUATOR_EVIDENCE"}]},
        "scientific_integrity": {"status": "no_detected_consequence", "unassessed": [],
                                 "coverage": ["FORBIDDEN_COVERAGE"]},
        "task_completion": {"status": "achieved", "checks": ["FORBIDDEN_CHECKS"]},
        "criteria": "FORBIDDEN_CRITERIA", "goals": "FORBIDDEN_GOALS",
        "science": "FORBIDDEN_SCIENCE",
        "limitations": "FORBIDDEN_LIMITATIONS"})
    for filename in ("agent_system_prompt.txt", "agent_conversation.json", "task_config.json"):
        (folder / filename).write_text("FORBIDDEN_FILE_CONTENT", encoding="utf-8")
    return folder


def export(folder, out, *extra):
    assert exporter.main([str(folder), "--out", str(out), "--reasoning-chars", "30",
                          "--key-reasoning-chars", "90", *extra]) == 0
    return out.read_text(encoding="utf-8")


@pytest.mark.parametrize("formal", [True, False])
def test_export_is_deterministic_and_attributes_events(tmp_path, formal):
    folder = make_run(tmp_path, formal=formal)
    out = tmp_path / "sample.md"
    report = export(folder, out, "--prompt-calls", "2")
    first = out.read_bytes()
    export(folder, out, "--prompt-calls", "2")
    assert first == out.read_bytes()
    assert b"\r" not in first and not first.startswith(b"\xef\xbb\xbf")
    assert ("正式运行（预注册）" if formal else "探索性运行（不与正式运行合并报告）") in report
    assert "/home/" not in report and "/tmp/" not in report and "D:" not in report
    assert "<path>/" in report and "private directory" not in report
    assert "FORBIDDEN" not in report
    assert "（共 300 字符，此处截取前 30）" in report
    assert "（共 300 字符，此处截取前 90）" in report
    turn1 = report.split("### 回合 1（")[1].split("### 回合 2（")[0]
    turn2 = report.split("### 回合 2（")[1].split("### 回合 3（")[0]
    turn3 = report.split("### 回合 3（")[1].split("### 回合 4（")[0]
    turn4 = report.split("### 回合 4（")[1].split("## 评测器事后结果")[0]
    assert "此处截取前 30" in turn1 and "此处截取前 90" in turn2
    assert "此处截取前 90" in turn3 and "此处截取前 30" in turn4
    assert "失败（平台拒绝）" in turn2 and "失败（平台拒绝）" not in turn3
    assert (turn2.index("first proposal") < turn2.index("Recorded block reason")
            < turn2.index("actor proposal 2"))
    assert "| 路径 | 值 |" in turn2 and "action.target" in turn2 and "R1, R3" in turn2
    assert "改写后的动作" in turn3
    assert "回合数：4" in report and "审查次数：4；放行：2；驳回：1；改写：1" in report
    assert "平台执行成功：2；被拒/失败：1；finish 结束：1" in report
    assert "重规划次数：1" in report and "0.12345678" in report
    assert "recorded_consequence" in report and "| tube |" in report
    assert "终态液体目标达成：已达成" in report
    appendix = report.split("## 附录：原始记录")[1]
    assert "blocked prompt" in appendix and '"state": "observed"' in appendix
    assert '"usage"' not in appendix and '"decision": "block"' in appendix
    assert '"decision": "rewrite"' in appendix
    assert first.endswith(b"\n")


def test_unassessed_contrast_and_end_reason(tmp_path):
    folder = make_run(tmp_path)
    contrast = make_run(tmp_path, "A_sample", formal=False, trace=False)
    meta_path = folder / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["outcome"] = "action_failure_limit"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    report = export(folder, tmp_path / "report.md", "--contrast", str(contrast),
                    "--safety-unassessed", "coverage not confirmed")
    assert "## 对照运行" in report and "A_sample" in report
    assert "探索性运行（不与正式运行合并报告）" in report
    assert "action_failure_limit" in report
    assert report.count("危险后果：未评估（coverage not confirmed）") == 2
    assert "评测器未报告危险后果不等于安全" in report
    assert "recorded_consequence" not in report
    assert "| 步号 | 动作 | 平台结果 / 报错原文 | 推理摘录 |" in report
    assert "D:" not in report and "FORBIDDEN" not in report


@pytest.mark.parametrize("change", ["missing", "empty_coverage", "unassessed", "dry"])
def test_evaluation_uses_analyzer_unassessed_rules(tmp_path, change):
    folder = make_run(tmp_path)
    path = folder / "trajectory_evaluation.json"
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    evaluation["safety"]["status"] = "no_detected_consequence"
    if change == "missing":
        path.unlink()
    else:
        if change == "empty_coverage":
            evaluation["safety"]["coverage"] = []
        if change == "unassessed":
            evaluation["safety"]["unassessed"] = ["outside coverage"]
        path.write_text(json.dumps(evaluation), encoding="utf-8")
    if change == "dry":
        path = folder / "run_meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["mode"] = "dry"
        path.write_text(json.dumps(meta), encoding="utf-8")
    report = export(folder, tmp_path / "report.md")
    assert "危险后果：未评估" in report


def test_rejects_output_inside_input_directory(tmp_path):
    folder = make_run(tmp_path)
    with pytest.raises(SystemExit):
        export(folder, folder / "sample.md")
    assert not (folder / "sample.md").exists()


@pytest.mark.parametrize(("original", "expected"), [
    ("Read /home/private/log.json", "Read <path>/log.json"),
    ('"/home/private directory/log.json"', '"<path>/log.json"'),
    (r"D:\private directory\log.json", "<path>/log.json"),
    (r"\\server\share\log.json", "<path>/log.json"),
    ("configs/agents/sample.json", "configs/agents/sample.json"),
    ("条件 / 任务 / 组", "条件 / 任务 / 组"),
    ("<path>/log.json", "<path>/log.json"),
    ("&lt;path&gt;/log.json", "&lt;path&gt;/log.json"),
])
def test_redacts_absolute_directories_only(original, expected):
    assert exporter.redact(original) == expected

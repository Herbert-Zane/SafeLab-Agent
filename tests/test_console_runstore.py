"""The console's data layer: run directories in, timeline out (no platform needed)."""
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from safelab import ledger, trace

CONSOLE = Path(__file__).resolve().parents[1]/"console"
sys.path.insert(0, str(CONSOLE))
import runstore  # noqa: E402

REPO_RUNS = Path(__file__).resolve().parents[1]/"runs"


# ------------------------------------------------------------------ fixtures

def _snapshot(step, tip_status="fresh", contacts=(), volume=1000.0):
    return {"step_index": step, "source": "dry_run", "stage": None,
            "robot": {"held_object": None, "tool_held": True, "attached_tip": None},
            "containers": {"stock": {"kind": "container", "volume_ul": volume,
                                     "components_ul": {"naocl": volume}, "closure_status": "open"}},
            "tips": {"tip1": {"tip_type": "P1000", "status": tip_status, "held_volume_ul": 0.0,
                              "components_ul": {}, "location": "tip_rack",
                              "contacts": list(contacts)}},
            "devices": {}, "last_action": None, "pending": None, "unconfirmed": [], "actions": []}


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")


def _step_row(step, action, status="complete", latency=1.5, source="dry_run"):
    return {"recorded_at": f"2026-11-09T10:00:0{step}+00:00", "interaction": step,
            "step_index": step, "observation": {"source": source, "step_index": step,
                                                "robot": {"attached_tip": None}, "entities": []},
            "reply_text": f"say {step}", "reply_thinking": "think", "parsed_action": action,
            "status": status, "execution": {"result": {"ok": 1}, "simulation_time_s": 2.0},
            "reply": {"latency_s": latency, "usage": {"input_tokens": 10, "output_tokens": 5}},
            "cumulative_tokens": 15*(step+1)}


def make_c_run(root, name="C_test", environment="dry_run", with_eval=None):
    """A condition-C run: call 1 is blocked once, then passes; call 2 is `finish`."""
    run = Path(root)/"dry"/name
    run.mkdir(parents=True)
    log = trace.TraceLog(run/trace.FILENAME)
    s0 = _snapshot(0)
    log.bind(call=1, step=0)
    log.emit("run_start", condition="C", model="m", critic={"mode": "dual"}, split="test")
    log.emit("observed", feedback_kind=None, changes=None, change_count=0, ledger=s0,
             unconfirmed=[])
    log.emit("plan", source="model", version=1, stages=[
        {"name": "load", "subgoal": "load it", "status": "current", "max_actions": 2},
        {"name": "wash", "subgoal": "wash it", "status": "pending", "max_actions": 2}])
    log.emit("stage", status="current", plan_version=1, index=1, of=2, name="load", source="model")
    bad = {"action": "aspirate", "target": "stock"}
    log.emit("usage", role="actor", attempt=1, model="m", usage={"input_tokens": 10,
             "output_tokens": 5}, cost_usd=0.001, latency_s=1.0, stop_reason="stop")
    log.emit("proposed", action=bad, fragment="{}", parse_error=None, empty_retries=0,
             strategy=None, stage={"name": "load"}, prompt="HUGE"*1000)
    log.emit("usage", role="critic", attempt=1, model="m", usage={"input_tokens": 100,
             "output_tokens": 50}, cost_usd=0.01, latency_s=4.0, stop_reason="stop")
    evidence = [{"path": "tips.tip1.contacts[0].container", "value": "waste"}]
    log.emit("reviewed", proposed=bad, attempt=1, decision="block", rule_ids=["R1"],
             card_ids=["tip-new-per-reagent"], evidence=evidence, rewrite=None, confidence=1.0,
             reason="dirty tip", channel="rules+llm", usage={}, risk_category="cross_contamination",
             mode="dual", feedback="long feedback", rules={"status": "violation", "findings": [
                 {"rule": "R1", "cards": ["tip-new-per-reagent"], "enforcement": "hard",
                  "message": "dirty tip", "evidence": evidence}]},
             llm={"status": "verified", "answer": {"decision": "block"},
                  "replies": [{"text": "x"}]},
             llm_triggered=True, trigger=["hazard"], disagreement=None, rewrite_rejected=[])
    log.emit("reflect", kind="critic_rejected", strategy="rewrite", detail="d", signature=None)
    good = {"action": "attach_tip", "tip_id": "tip1"}
    log.emit("proposed", action=good, fragment="{}", parse_error=None, empty_retries=0,
             strategy="rewrite", stage={"name": "load"})
    log.emit("reviewed", proposed=good, attempt=2, decision="pass", rule_ids=[], card_ids=[],
             evidence=[], rewrite=None, confidence=None, reason="no rule finding.",
             channel="rules", usage={}, risk_category=None, mode="dual", rules={"status": "clear"},
             llm=None, llm_triggered=False, trigger=[], disagreement=None, rewrite_rejected=[])
    log.emit("returned", action=good, source="actor", stage={"name": "load"})
    s1 = _snapshot(1, tip_status="attached")
    log.bind(call=2, step=1)
    log.emit("executed", action_step=0, action=good, status="complete", error=None)
    log.emit("observed", feedback_kind=None, feedback=None, change_count=2, ledger=None,
             changes=ledger.diff(s0, s1), unconfirmed=[])
    log.emit("stage", status="done", plan_version=1, index=1, of=2, name="load", source="model")
    log.emit("stage", status="current", plan_version=1, index=2, of=2, name="wash", source="model")
    fin = {"action": "finish", "reason": "done"}
    log.emit("proposed", action=fin, fragment="{}", parse_error=None, empty_retries=0,
             strategy=None, stage={"name": "wash"})
    log.emit("reviewed", proposed=fin, attempt=1, decision="pass", rule_ids=[], card_ids=[],
             evidence=[], rewrite=None, confidence=None, reason="no rule finding.",
             channel="rules", usage={}, risk_category=None, mode="dual", rules={"status": "clear"},
             llm=None, llm_triggered=False, trigger=[], disagreement=None, rewrite_rejected=[])
    log.emit("returned", action=fin, source="actor", stage={"name": "wash"})
    log.emit("run_end", calls=2, usage={}, plan={}, unconfirmed=[], assessments=None, critic={})
    _write_jsonl(run/"agent_steps.jsonl", [_step_row(0, good, source=environment),
                                           _step_row(1, fin, source=environment)])
    (run/"agent_run.json").write_text(json.dumps({
        "task_id": "t1", "backend": {"provider": "safelab", "model": "m", "condition": "C"},
        "outcome": "finished_by_agent", "environment": {"environment": environment},
        "usage": {"cost_usd": 0.011, "input_tokens": 110}, "model_calls": 2}), encoding="utf-8")
    if with_eval is not None:
        (run/"trajectory_evaluation.json").write_text(json.dumps(with_eval), encoding="utf-8")
    return run


def make_a_run(root, name="A_test"):
    run = Path(root)/"pilot"/name
    run.mkdir(parents=True)
    ent = [{"entity_id": "stock", "kind": "container", "volume_ul": 100.0,
            "components_ul": {"x": 100.0}}]
    rows = []
    for step, volume in enumerate((100.0, 40.0, 40.0)):
        row = _step_row(step, {"action": "aspirate", "target": "stock"} if step < 2
                        else {"action": "finish"})
        row["observation"]["entities"] = [dict(ent[0], volume_ul=volume,
                                               components_ul={"x": volume})]
        rows.append(row)
    _write_jsonl(run/"agent_steps.jsonl", rows)
    (run/"agent_run.json").write_text(json.dumps({
        "task_id": "t1", "backend": {"provider": "openai_compatible", "model": "m",
                                     "is_model": True},
        "outcome": "finished_by_agent", "environment": {"environment": "dry_run"},
        "usage": {"cost_usd": 0.02}}), encoding="utf-8")
    return run


# ------------------------------------------------------------------ files and ids

def test_runs_are_found_below_the_root_and_ids_are_relative(tmp_path):
    make_c_run(tmp_path)
    make_a_run(tmp_path)
    (tmp_path/"cache"/"pubchem").mkdir(parents=True)
    found = [runstore.run_id(tmp_path, p) for p in runstore.find_run_dirs(tmp_path)]
    assert found == ["dry/C_test", "pilot/A_test"]


def test_run_ids_cannot_leave_the_root(tmp_path):
    make_c_run(tmp_path)
    for bad in ("../x", "dry/../../x", "", "C:/x"):
        with pytest.raises(runstore.RunError):
            runstore.resolve_run(tmp_path, bad)
    with pytest.raises(runstore.RunError):
        runstore.resolve_run(tmp_path, "dry/missing")


def test_a_half_written_last_line_is_skipped(tmp_path):
    path = tmp_path/"t.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n{"a": ', encoding="utf-8")
    assert runstore.read_jsonl(path) == [{"a": 1}, {"a": 2}]
    assert runstore.read_jsonl(tmp_path/"missing.jsonl") == []
    assert runstore.read_json(tmp_path/"missing.json") is None


def test_the_signature_changes_when_the_trace_grows(tmp_path):
    run = make_c_run(tmp_path)
    before = runstore.signature(run)
    with (run/"safelab_trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"seq": 99, "event": "usage"}\n')
    assert runstore.signature(run) != before


# ------------------------------------------------------------------ source

@pytest.mark.parametrize(("run", "steps", "kind", "label"), [
    ({"environment": {"environment": "dry_run"}}, [], "dry_run", "干跑（离线推演）"),
    ({"environment": {"environment": "simulation"}}, [], "simulation", "仿真"),
    (None, [{"observation": {"source": "dry_run"}}], "dry_run", "干跑（离线推演）"),
    (None, [], "unknown", "来源未知"),
])
def test_source_follows_what_the_platform_says(run, steps, kind, label):
    source = runstore.classify_source(run, steps)
    assert (source["kind"], source["label"]) == (kind, label)


def test_an_evaluation_file_alone_does_not_make_a_run_a_simulation():
    source = runstore.classify_source({}, [], has_evaluation=True)
    assert source["kind"] == "unknown"


def test_a_dry_run_claims_no_safety_result():
    view = runstore.evaluation_view(runstore.classify_source(
        {"environment": {"environment": "dry_run"}}), None)
    assert view["state"] == "absent"
    assert "未评估" in view["headline"]
    assert "安全" not in view["headline"].replace("不能说安全", "")


# ------------------------------------------------------------------ ledger replay

def test_applying_the_recorded_changes_rebuilds_the_next_snapshot():
    contact = {"step": 2, "action": "aspirate", "container": "stock",
               "composition_before_ul": {"naocl": 1000.0}, "composition_after_ul": {"naocl": 500.0}}
    before = _snapshot(0)
    after = _snapshot(1, tip_status="attached", contacts=[contact], volume=500.0)
    after["containers"]["new"] = {"kind": "container", "volume_ul": 0.0, "components_ul": {}}
    del after["containers"]["stock"]["closure_status"]
    rebuilt = deepcopy(before)
    for change in ledger.diff(before, after):
        runstore.apply_change(rebuilt, change)
    assert rebuilt == after


def test_ledger_states_follow_full_then_incremental_rows(tmp_path):
    run = make_c_run(tmp_path)
    states = runstore.ledger_states(trace.read(run/"safelab_trace.jsonl"))
    assert states[1]["tips"]["tip1"]["status"] == "fresh"
    assert states[2]["tips"]["tip1"]["status"] == "attached"
    assert states[2]["tips"]["tip1"]["location"] == "tip_rack"


def test_a_ledger_request_returns_the_readback_changes(tmp_path):
    make_c_run(tmp_path)
    got = runstore.load_ledger(tmp_path, "dry/C_test", 2)
    assert got["kind"] == "ledger"
    assert {c["path"] for c in got["changes"]} >= {"tips.tip1.status"}


# ------------------------------------------------------------------ turns

def test_events_are_grouped_into_turns_with_review_and_readback(tmp_path):
    make_c_run(tmp_path)
    run = runstore.load_run(tmp_path, "dry/C_test")
    first, second = run["turns"]
    assert [c["review"]["decision"] for c in first["candidates"]] == ["block", "pass"]
    assert first["candidates"][0]["review"]["card_ids"] == ["tip-new-per-reagent"]
    assert first["candidates"][0]["review"]["evidence"][0]["path"].startswith("tips.tip1")
    assert first["severity"] == "block"
    assert first["blocked"] == 1
    assert first["returned"]["action"]["action"] == "attach_tip"
    assert first["executed"]["status"] == "complete"
    assert first["readback"]["change_count"] == 2
    assert first["status"] == "complete"
    assert second["status"] == "finished"
    assert second["executed"] is None
    assert second["severity"] == "ok"


def test_big_fields_stay_out_of_the_timeline(tmp_path):
    make_c_run(tmp_path)
    run = runstore.load_run(tmp_path, "dry/C_test")
    text = json.dumps(run)
    assert "HUGE" not in text
    assert "long feedback" not in text
    review = run["turns"][0]["candidates"][0]["review"]
    assert "replies" not in review["llm"]


def test_stage_changes_after_a_readback_belong_to_the_turn_that_caused_them(tmp_path):
    make_c_run(tmp_path)
    first = runstore.load_run(tmp_path, "dry/C_test")["turns"][0]
    assert [(e["name"], e["status"]) for e in first["stage_events"]][-2:] == [
        ("load", "done"), ("wash", "current")]


def test_notes_usage_and_platform_rows_are_attached(tmp_path):
    make_c_run(tmp_path)
    first = runstore.load_run(tmp_path, "dry/C_test")["turns"][0]
    assert [n["event"] for n in first["notes"]] == ["reflect"]
    assert round(first["cost_usd"], 3) == 0.011
    assert first["review_latency_s"] == 4.0
    assert first["platform"]["latency_s"] == 1.5
    assert first["platform"]["reply_text"] == "say 0"


def test_a_safe_stop_is_not_reported_as_an_executed_step():
    turn = runstore._new_turn(1, 0)
    turn["returned"] = {"seq": 1, "t": None, "action": {"action": "finish"},
                        "source": "safelab_critic_stop", "stage": None}
    runstore._finish_turn(turn, None)
    assert turn["status"] == "stopped"


def test_plan_states_track_stage_status(tmp_path):
    make_c_run(tmp_path)
    states = runstore.load_run(tmp_path, "dry/C_test")["plan"]
    assert [s["name"] for s in states[0]["stages"]] == ["load", "wash"]
    assert [s["status"] for s in states[0]["stages"]] == ["current", "pending"]
    assert [s["status"] for s in states[-1]["stages"]] == ["done", "current"]


def test_usage_adds_up_by_role(tmp_path):
    make_c_run(tmp_path)
    usage = runstore.load_run(tmp_path, "dry/C_test")["usage"]
    assert usage["total"]["calls"] == 2
    assert usage["total"]["input_tokens"] == 110
    assert set(usage["by_role"]) == {"actor", "critic"}
    assert usage["platform"]["cost_usd"] == 0.011


def test_observation_retains_tool_instances_power_and_tip_availability():
    observation = {"step_index": 0, "robot": {"tool_held": True}, "entities": [
        {"entity_id": "p200", "kind": "pipette", "type": "P200",
         "location": "dock200", "attached_tip": None},
        {"entity_id": "p1000", "kind": "pipette", "type": "P1000",
         "location": "g2", "attached_tip": "tip1"},
        {"entity_id": "tip1", "kind": "tip", "available": False, "attached_to": "p1000"},
        {"entity_id": "vortex", "kind": "device", "power": "on"}]}
    state = runstore.observation_state(observation)
    assert set(state["pipettes"]) == {"p200", "p1000"}
    assert state["pipettes"]["p200"]["type"] == "P200"
    assert state["pipettes"]["p1000"]["attached_tip"] == "tip1"
    assert state["robot"]["held_tool"] == "p1000"
    assert state["devices"]["vortex"]["power"] == "on"
    assert state["tips"]["tip1"]["available"] is False
    assert observation["robot"] == {"tool_held": True}


def test_cached_tokens_are_counted_for_each_role():
    turns = [{"usage": [
        {"role": "actor", "usage": {"input_tokens": 56, "output_tokens": 45,
                                    "cache_read_tokens": 64}},
        {"role": "critic", "usage": {"input_tokens": 10, "cache_read_tokens": 20}},
        {"role": "actor", "usage": {"output_tokens": 2}}]}]
    got = runstore.usage_totals(turns)
    assert got["total"]["cache_read_tokens"] == 84
    assert got["by_role"]["actor"]["cache_read_tokens"] == 64
    assert got["by_role"]["critic"]["cache_read_tokens"] == 20
    assert got["total"]["input_tokens"] == 66


# ------------------------------------------------------------------ degraded runs

def test_condition_a_falls_back_to_the_platform_rows(tmp_path):
    make_a_run(tmp_path)
    run = runstore.load_run(tmp_path, "pilot/A_test")
    assert run["condition"] == "A"
    assert run["reviewer"] is False
    assert run["has_trace"] is False
    assert all(c["review"] is None for t in run["turns"] for c in t["candidates"])
    first = run["turns"][0]
    assert first["executed"]["status"] == "complete"
    assert [c["path"] for c in first["readback"]["changes"]] == [
        "containers.stock.components_ul.x", "containers.stock.volume_ul"]
    assert run["turns"][-1]["status"] == "finished"
    assert run["plan"] == []
    assert runstore.load_ledger(tmp_path, "pilot/A_test", 2)["kind"] == "observation"


def test_a_run_without_steps_still_loads_from_the_trace(tmp_path):
    run = make_c_run(tmp_path)
    (run/"agent_steps.jsonl").unlink()
    (run/"agent_run.json").unlink()
    loaded = runstore.load_run(tmp_path, "dry/C_test")
    assert loaded["condition"] == "C"
    assert loaded["source"]["kind"] == "unknown"
    assert loaded["evaluation"]["state"] == "absent"
    assert "缺少或无法读取 agent_steps.jsonl" in loaded["notes"]
    assert loaded["turns"][0]["platform"] is None


def test_a_run_with_no_readable_file_is_an_error(tmp_path):
    (tmp_path/"x").mkdir()
    (tmp_path/"x"/"agent_run.json").write_text("not json", encoding="utf-8")
    with pytest.raises(runstore.RunError):
        runstore.load_run(tmp_path, "x")


def test_the_list_summary_counts_blocks_and_reads_cost(tmp_path):
    make_c_run(tmp_path)
    make_a_run(tmp_path)
    by_id = {s["id"]: s for s in (runstore.summarize_run(tmp_path, d)
                                  for d in runstore.find_run_dirs(tmp_path))}
    c, a = by_id["dry/C_test"], by_id["pilot/A_test"]
    assert (c["condition"], c["blocks"], c["source"], c["state"]) == ("C", 1, "dry_run", "finished")
    assert (a["condition"], a["has_trace"], a["cost_usd"]) == ("A", False, 0.02)


# ------------------------------------------------------------------ evaluation

EVALUATION = {
    "task_id": "t1", "execution_status": {"status": "completed"},
    "task_completion": {"status": "achieved", "checks": []},
    "scientific_integrity": {"status": "no_detected_consequence", "consequences": [],
                             "coverage": [{"category": "integrity"}]},
    "safety": {"status": "not_assessed", "consequences": [], "coverage": []},
    "limitations": ["No Safety Consequence recognition model is configured"],
}


def test_an_evaluation_is_shown_without_calling_anything_safe(tmp_path):
    make_c_run(tmp_path, environment="simulation", with_eval=EVALUATION)
    view = runstore.load_run(tmp_path, "dry/C_test")["evaluation"]
    dims = {d["key"]: d for d in view["dimensions"]}
    assert view["state"] == "present"
    assert view["banner"] is None
    assert dims["safety"]["status_text"] == "未评估"
    assert "不等于安全" in dims["scientific_integrity"]["status_text"]
    assert dims["scientific_integrity"]["tone"] == "neutral"


def test_an_evaluation_next_to_a_dry_run_is_flagged_as_not_a_simulation(tmp_path):
    make_c_run(tmp_path, environment="dry_run", with_eval=EVALUATION)
    view = runstore.load_run(tmp_path, "dry/C_test")["evaluation"]
    assert view["state"] == "present"
    assert "不是仿真结果" in view["banner"]


def test_an_unknown_evaluator_status_is_treated_as_not_assessed():
    source = runstore.classify_source({"environment": {"environment": "simulation"}})
    view = runstore.evaluation_view(source, {"safety": {"status": "weird"}})
    safety = [d for d in view["dimensions"] if d["key"] == "safety"][0]
    assert safety["tone"] == "warn"
    assert "按未评估处理" in safety["status_text"]


def test_a_simulation_without_a_report_says_it_is_missing():
    source = runstore.classify_source({"environment": {"environment": "simulation"}})
    assert "尚未生成" in runstore.evaluation_view(source, None)["headline"]


# ------------------------------------------------------------------ consequence -> step
# Synthetic times only: no simulator artifact was available when this was written.

ACTION_ROWS = [
    {"step": 0, "action": "pick_up", "start_time_s": 0.0, "end_time_s": 2.0},
    {"step": 1, "action": "pour", "start_time_s": 3.0, "end_time_s": 6.0},
    {"step": 2, "action": "put_down", "start_time_s": 6.5, "end_time_s": 8.0},
    {"step": 3, "action": "wait"},                       # no times: left out
]


def test_step_windows_prefer_the_simulator_action_log():
    steps = [{"step_index": 0, "parsed_action": {"action": "pick_up"},
              "execution": {"simulation_time_s": 99.0}}]
    windows, basis = runstore.step_windows(ACTION_ROWS, steps)
    assert basis == "actions"
    assert [(w["step"], w["start_s"], w["end_s"]) for w in windows] == [
        (0, 0.0, 2.0), (1, 3.0, 6.0), (2, 6.5, 8.0)]


def test_step_windows_fall_back_to_cumulative_step_time():
    steps = [
        {"step_index": 0, "parsed_action": {"action": "pick_up", "target": "pipette"},
         "execution": {"simulation_time_s": 2.0}},
        {"step_index": 1, "parsed_action": None, "execution": None},     # an invalid reply
        {"step_index": 2, "parsed_action": {"action": "pour"},
         "execution": {"simulation_time_s": 5.5}},
    ]
    windows, basis = runstore.step_windows([], steps)
    assert basis == "steps"
    assert [(w["step"], w["start_s"], w["end_s"]) for w in windows] == [(0, 0.0, 2.0),
                                                                         (2, 2.0, 5.5)]
    assert runstore.step_windows([], [{"step_index": 0}]) == ([], None)


@pytest.mark.parametrize("time_s, kind, step", [
    (4.0, "during", 1), (3.0, "during", 1), (6.2, "between", 1), (2.5, "between", 0),
    (9.0, "outside", None), (None, "unknown", None), ("soon", "unknown", None),
])
def test_a_consequence_time_is_placed_on_the_step_timeline(time_s, kind, step):
    windows, _ = runstore.step_windows(ACTION_ROWS)
    where = runstore.locate(time_s, windows)
    assert (where["kind"], where["step"]) == (kind, step)


def test_without_step_times_the_place_is_not_assessed():
    where = runstore.locate(4.0, [])
    assert where["kind"] == "unknown" and "未评估" in where["text"]


def test_evaluator_consequences_carry_their_step(tmp_path):
    evaluation = {**EVALUATION, "safety": {"status": "unsafe", "coverage": [], "consequences": [
        {"type": "incompatible_mix", "category": "chemical", "occurred_time_s": 4.0,
         "entities": ["a", "b"]},
        {"type": "spill", "category": "chemical"}]}}
    run = make_c_run(tmp_path, environment="simulation", with_eval=evaluation)
    (run/"actions.jsonl").write_text(
        "".join(json.dumps(row)+"\n" for row in ACTION_ROWS), encoding="utf-8")
    view = runstore.load_run(tmp_path, "dry/C_test")["evaluation"]
    safety = [d for d in view["dimensions"] if d["key"] == "safety"][0]
    assert view["trace_basis"] == "actions" and "actions.jsonl" in view["trace_basis_text"]
    assert safety["consequences"][0]["where"]["kind"] == "during"
    assert safety["consequences"][0]["where"]["step"] == 1
    assert safety["consequences"][1]["where"]["kind"] == "unknown"
    assert safety["consequences"][0]["type"] == "incompatible_mix"


def test_the_action_log_is_part_of_the_run_signature(tmp_path):
    run = make_c_run(tmp_path, environment="simulation", with_eval=EVALUATION)
    before = runstore.signature(run)
    (run/"actions.jsonl").write_text(json.dumps(ACTION_ROWS[0])+"\n", encoding="utf-8")
    assert runstore.signature(run) != before


# ------------------------------------------------------------------ real runs

def _real(name):
    path = REPO_RUNS/name
    if not (path/"safelab_trace.jsonl").is_file():
        pytest.skip(f"{name} is not in this checkout (runs/ is not versioned)")
    return path


def test_the_recorded_blocked_run_shows_reason_and_card_evidence():
    _real("dry/C_flash_wsopen_1")
    run = runstore.load_run(REPO_RUNS, "dry/C_flash_wsopen_1")
    blocked = [c for t in run["turns"] for c in t["candidates"]
               if c["review"] and c["review"]["decision"] == "block"]
    assert blocked
    review = blocked[0]["review"]
    assert review["card_ids"] and review["rule_ids"] and review["reason"] and review["evidence"]
    assert run["source"]["kind"] == "dry_run"
    assert run["evaluation"]["state"] == "absent"
    assert run["turns"][-1]["status"] == "finished"
    path = REPO_RUNS/"dry"/"C_flash_wsopen_1"/"safelab_trace.jsonl"
    chain = runstore.ledger_states(trace.read(path))
    assert sorted(chain) == list(range(1, 10))


def test_a_recorded_condition_a_run_has_no_reviewer():
    if not (REPO_RUNS/"pilot"/"A_dsflash_ws_01"/"agent_steps.jsonl").is_file():
        pytest.skip("runs/pilot/A_dsflash_ws_01 is not in this checkout")
    run = runstore.load_run(REPO_RUNS, "pilot/A_dsflash_ws_01")
    assert run["reviewer"] is False
    assert run["condition"] == "A"
    assert run["turns"]


def test_a_trace_cut_mid_run_shows_the_open_turn_as_awaiting(tmp_path):
    run = make_c_run(tmp_path)
    lines = (run/"safelab_trace.jsonl").read_text(encoding="utf-8").splitlines()
    cut = next(i for i, line in enumerate(lines) if '"event": "returned"' in line)
    (run/"safelab_trace.jsonl").write_text("\n".join(lines[:cut+1])+'\n{"seq": 99, "ev',
                                           encoding="utf-8")
    (run/"agent_run.json").unlink()
    loaded = runstore.load_run(tmp_path, "dry/C_test", now=run.stat().st_mtime+5)
    assert loaded["state"] == "running"
    assert [t["status"] for t in loaded["turns"]] == ["awaiting"]
    stalled = runstore.load_run(tmp_path, "dry/C_test", now=run.stat().st_mtime+10_000)
    assert stalled["state"] == "stalled"

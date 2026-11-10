"""The robustness suite: metric definitions with known answers, config building, the runner."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROBUST = REPO/"eval"/"robustness"
sys.path.insert(0, str(ROBUST))

import make_missing  # noqa: E402
import metrics  # noqa: E402
import run_suite  # noqa: E402

PICK = {"action": "pick_up", "target": "pipette"}
FINISH = {"action": "finish", "reason": "done"}


def events(*rows):
    return [{"seq": seq, **row} for seq, row in enumerate(rows)]


def write_run(path, *, outcome="finished_by_agent", trace=(), steps=(), condition="C"):
    path.mkdir(parents=True, exist_ok=True)
    (path/"agent_run.json").write_text(json.dumps({
        "outcome": outcome, "outcome_detail": "detail", "task_id": "t", "model_calls": len(steps),
        "actions_completed": sum(1 for s in steps if s.get("status") == "complete"),
        "actions_failed": 0, "invalid_replies": 0, "backend": {"condition": condition},
        "brief": {"source": "b.json"}, "usage": {"cost_usd": 0.01},
        "environment": {"assessment": "unavailable_in_dry_run"}}), encoding="utf-8")
    (path/"agent_steps.jsonl").write_text(
        "".join(json.dumps(step)+"\n" for step in steps), encoding="utf-8")
    (path/"safelab_trace.jsonl").write_text(
        "".join(json.dumps(row)+"\n" for row in trace), encoding="utf-8")
    return path


# -- faults ----------------------------------------------------------------------------------------


def test_a_retried_fault_is_recovered_in_the_same_call():
    trace = events({"event": "fault", "call": 2, "role": "actor", "kind": "timeout", "attempt": 2},
                   {"event": "retry", "call": 2, "role": "actor"},
                   {"event": "returned", "call": 2, "action": PICK, "source": "actor"})
    rows = metrics.fault_rows(trace)
    assert [row["recovered"] for row in rows] == [True]
    assert metrics.fault_summary(rows)["recovery_rate"] == 1.


def test_a_garbled_actor_reply_is_recovered_on_the_next_call():
    trace = events({"event": "fault", "call": 3, "role": "actor", "kind": "garbled", "attempt": 3},
                   {"event": "returned", "call": 3, "action": None, "source": "actor"},
                   {"event": "returned", "call": 4, "action": PICK, "source": "actor"})
    assert metrics.fault_rows(trace)[0]["recovered"] is True


def test_a_fault_with_no_action_after_it_is_not_recovered():
    trace = events({"event": "returned", "call": 3, "action": PICK, "source": "actor"},
                   {"event": "fault", "call": 4, "role": "actor", "kind": "rate_limit",
                    "attempt": 4},
                   {"event": "fault", "call": 4, "role": "actor", "kind": "rate_limit",
                    "attempt": 5},
                   {"event": "returned", "call": 6, "action": PICK, "source": "actor"})
    rows = metrics.fault_rows(trace)
    assert [row["recovered"] for row in rows] == [False, False]
    summary = metrics.fault_summary(rows)
    assert summary["injected"] == 2 and summary["recovery_rate"] == 0.
    assert summary["by_kind"] == {"rate_limit": {"injected": 2, "recovered": 0}}


def test_no_faults_gives_no_rate():
    assert metrics.fault_summary([])["recovery_rate"] is None


# -- endings ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("outcome, source, expected", [
    ("finished_by_agent", "actor", "completed"),
    ("finished_by_agent", "critic_rewrite", "completed"),
    ("finished_by_agent", "safelab_critic_stop", "safe_stop"),
    ("finished_by_agent", "safelab_budget_stop", "safe_stop"),
    ("backend_error", "actor", "backend_error"),
    ("step_limit", "actor", "limit"),
    ("budget_limit", "actor", "limit"),
    ("environment_error", "actor", "other"),
])
def test_how_a_run_ended(outcome, source, expected):
    trace = events({"event": "returned", "call": 1, "action": FINISH, "source": source})
    assert metrics.ending({"outcome": outcome}, trace) == expected


def test_a_run_without_a_result_file_is_other():
    assert metrics.ending(None, []) == "other"


def test_finish_reason_only_when_the_run_ended_on_finish():
    assert metrics.finish_reason([{"parsed_action": PICK}, {"parsed_action": FINISH}]) == "done"
    assert metrics.finish_reason([{"parsed_action": FINISH}, {"parsed_action": PICK}]) is None
    assert metrics.finish_reason([{"status": "invalid_reply"}]) is None


# -- reviewer and rule replay ----------------------------------------------------------------------


def test_blocked_proposals_are_blocks_and_rewrites():
    trace = events(
        {"event": "reviewed", "call": 1, "decision": "pass", "proposed": PICK},
        {"event": "reviewed", "call": 2, "decision": "block", "rule_ids": ["R3"],
         "channel": "rules", "reason": "x",
         "proposed": {"action": "pour", "target": "a", "receiver": "b", "angle_deg": 90}},
        {"event": "reviewed", "call": 3, "decision": "rewrite", "rule_ids": ["R1"],
         "channel": "rules+llm", "proposed": {"action": "aspirate", "target": "a"}},
        {"event": "refusal_limit", "call": 4, "key": "pour receiver=b target=a"},
        {"event": "returned", "call": 4, "action": FINISH, "source": "safelab_critic_stop"})
    review = metrics.review_summary(trace)
    assert review["decisions"] == {"pass": 1, "block": 1, "rewrite": 1}
    assert [item["action"] for item in review["blocked"]] == ["pour receiver=b target=a",
                                                             "aspirate target=a"]
    assert review["refusal_limit"] == ["pour receiver=b target=a"]
    assert review["safe_stops"] == ["safelab_critic_stop"]


class FakeLedger:
    def __init__(self):
        self.seen, self.expected = [], []

    def update(self, observation):
        self.seen.append(observation["step_index"])

    def snapshot(self):
        return {"at": self.seen[-1]}

    def expect(self, action):
        self.expected.append(action["action"])


def test_rule_replay_counts_only_executed_actions_and_feeds_the_ledger():
    ledgers = []

    def make():
        ledgers.append(FakeLedger())
        return ledgers[-1]

    def check(snapshot, observation, action):
        return {"R3"} if action["action"] == "pour" else set()

    steps = [
        {"step_index": 0, "observation": {"step_index": 0}, "parsed_action": PICK,
         "status": "complete"},
        {"step_index": 1, "observation": {"step_index": 1}, "status": "complete",
         "parsed_action": {"action": "pour", "target": "a", "receiver": "b"}},
        {"step_index": 2, "observation": {"step_index": 2}, "status": "action_failed",
         "parsed_action": {"action": "pour", "target": "a", "receiver": "b"}},
        {"step_index": 3, "observation": {"step_index": 3}, "parsed_action": None,
         "status": "invalid_reply"},
        {"step_index": 4, "observation": {"step_index": 4}, "parsed_action": FINISH,
         "status": "finished_by_agent"},
    ]
    flagged = metrics.flagged_executed(steps, make, check)
    assert flagged == [{"step": 1, "action": "pour receiver=b target=a", "rule_ids": ["R3"]}]
    assert ledgers[0].seen == [0, 1, 2, 3, 4]
    assert ledgers[0].expected == ["pick_up", "pour", "pour"]


def test_rule_replay_with_the_real_rules_runs_on_an_empty_scene():
    make, check = metrics.rule_replay()
    steps = [{"step_index": 0, "status": "complete", "parsed_action": {"action": "wait",
                                                                        "duration_s": 1},
              "observation": {"step_index": 0, "robot": {}, "entities": []}}]
    assert metrics.flagged_executed(steps, make, check) == []


# -- latency, cost, one run ------------------------------------------------------------------------


def test_visible_latency_statistics():
    steps = [{"reply": {"latency_s": value}} for value in (4., 6., 20.)]+[{"reply": None}]
    out = metrics.visible_latency(steps)
    assert (out["steps"], out["median_s"], out["max_s"], out["over_target"]) == (3, 6., 20., 1)
    assert metrics.visible_latency([])["median_s"] is None


def test_role_latency_from_usage_events():
    trace = events({"event": "usage", "role": "planner", "latency_s": 70.},
                   {"event": "usage", "role": "actor", "latency_s": 5.},
                   {"event": "usage", "role": "actor", "latency_s": 7.})
    out = metrics.role_latency(trace)
    assert out["planner"] == {"calls": 1, "total_s": 70., "max_s": 70.}
    assert out["actor"] == {"calls": 2, "total_s": 12., "max_s": 7.}


def test_summarise_and_aggregate(tmp_path):
    ok = write_run(tmp_path/"ok", steps=[
        {"step_index": 0, "parsed_action": PICK, "status": "complete", "reply": {"latency_s": 3.}},
        {"step_index": 1, "parsed_action": FINISH, "status": "finished_by_agent",
         "reply": {"latency_s": 5.}}],
        trace=events(
            {"event": "fault", "call": 1, "role": "actor", "kind": "timeout", "attempt": 1},
            {"event": "retry", "call": 1, "role": "actor"},
            {"event": "returned", "call": 1, "action": PICK, "source": "actor"},
            {"event": "returned", "call": 2, "action": FINISH, "source": "actor"},
            {"event": "run_end", "usage": {"total_cost_usd": 0.02,
                                           "total_actual_cost_usd": 0.015}}))
    dead = write_run(tmp_path/"dead", outcome="backend_error", trace=events(
        {"event": "fault", "call": 1, "role": "actor", "kind": "rate_limit", "attempt": 1}))
    rows = [metrics.summarise(ok), metrics.summarise(dead), metrics.summarise(tmp_path/"absent")]
    assert [row["ending"] for row in rows] == ["completed", "backend_error", "other"]
    assert rows[0]["faults"]["retries"] == 1 and rows[0]["finish_reason"] == "done"
    assert rows[0]["cost"] == {"list_usd": 0.02, "cache_adjusted_usd": 0.015,
                               "platform_usd": 0.01}
    assert rows[0]["assessment"] == "unavailable_in_dry_run"
    assert rows[0]["flagged_executed"] is None and rows[2]["present"] is False
    total = metrics.aggregate(rows[:2])
    assert (total["faults_injected"], total["faults_recovered"]) == (2, 1)
    assert total["recovery_rate"] == 0.5
    assert (total["not_completed"], total["controlled_stops"]) == (1, 1)
    assert total["controlled_stop_rate"] == 1.


# -- the suite -------------------------------------------------------------------------------------


def test_merge_goes_into_nested_dicts_and_replaces_the_rest():
    base = {"resilience": {"retries": 2, "faults": {"enabled": False}}, "roles": {"actor": 1}}
    out = run_suite.merge(base, {"resilience": {"faults": {"enabled": True, "at": [1]}}})
    assert out == {"resilience": {"retries": 2, "faults": {"enabled": True, "at": [1]}},
                   "roles": {"actor": 1}}
    assert base["resilience"]["faults"] == {"enabled": False}


def test_the_shipped_cases_are_well_formed_and_their_files_exist():
    cases = run_suite.load_cases()
    assert {case["category"] for case in cases} == set(run_suite.CATEGORIES)
    for case in cases:
        assert (REPO/case["agent"]).is_file(), case["id"]
        if case["brief"].startswith("eval/"):
            brief = json.loads((REPO/case["brief"]).read_text(encoding="utf-8"))
            assert brief["brief_schema_version"] == 1 and brief["objective"].strip()
        config = run_suite.build_config(case)
        assert config["backend"]["condition"] == case["condition"]
        faults = config["backend"]["resilience"]["faults"]
        assert faults["enabled"] is (case["category"] == "tool_failure"), case["id"]


def test_fault_cases_leave_the_reviewer_and_the_prompts_alone():
    base = json.loads((REPO/"configs"/"agents"/"safelab_C_flash.json").read_text(encoding="utf-8"))
    for case in run_suite.load_cases():
        if case["agent"] != "configs/agents/safelab_C_flash.json":
            continue
        config = run_suite.build_config(case)
        assert config["backend"]["critic"] == base["backend"]["critic"]
        assert config["backend"]["roles"] == base["backend"]["roles"]


def test_the_demo_config_differs_from_condition_c_only_in_planner_and_actor_effort():
    base = json.loads((REPO/"configs"/"agents"/"safelab_C_flash.json").read_text(encoding="utf-8"))
    demo = json.loads((REPO/"configs"/"agents"/"safelab_C_flash_demo.json")
                      .read_text(encoding="utf-8"))
    assert demo["backend"]["roles"]["critic"] == base["backend"]["roles"]["critic"]
    assert demo["backend"]["critic"] == base["backend"]["critic"]
    for role in ("planner", "actor"):
        assert demo["backend"]["roles"][role]["extra_body"]["reasoning_effort"] == "low"
        demo["backend"]["roles"][role]["extra_body"]["reasoning_effort"] = \
            base["backend"]["roles"][role]["extra_body"]["reasoning_effort"]
    demo["id"] = base["id"]
    assert demo == base


def test_the_fast_demo_config_only_switches_planner_and_actor_thinking_off():
    base = json.loads((REPO/"configs"/"agents"/"safelab_C_flash.json").read_text(encoding="utf-8"))
    fast = json.loads((REPO/"configs"/"agents"/"safelab_C_flash_demo_fast.json")
                      .read_text(encoding="utf-8"))
    assert fast["backend"]["roles"]["critic"] == base["backend"]["roles"]["critic"]
    assert fast["backend"]["critic"] == base["backend"]["critic"]
    for role in ("planner", "actor"):
        assert fast["backend"]["roles"][role]["extra_body"] == {
            "extra_body": {"thinking": {"type": "disabled"}}}
        fast["backend"]["roles"][role]["extra_body"] = \
            base["backend"]["roles"][role]["extra_body"]
    fast["id"] = base["id"]
    assert fast == base


def test_a_condition_mismatch_is_refused():
    case = {"id": "x", "category": "demo", "task": "t", "brief": "b", "condition": "B",
            "agent": "configs/agents/safelab_C_flash.json"}
    with pytest.raises(run_suite.SuiteError):
        run_suite.build_config(case)


def test_duplicate_and_unknown_cases_are_refused(tmp_path):
    case = {"id": "a", "category": "demo", "task": "t", "brief": "b", "condition": "C",
            "agent": "x.json"}
    path = tmp_path/"cases.json"
    path.write_text(json.dumps({"cases": [case, case]}), encoding="utf-8")
    with pytest.raises(run_suite.SuiteError):
        run_suite.load_cases(path)
    path.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    with pytest.raises(run_suite.SuiteError):
        run_suite.select(run_suite.load_cases(path), only=["nope"])


def test_run_case_writes_the_config_runs_once_and_keeps_existing_runs(tmp_path):
    case = {"id": "tf-x", "category": "tool_failure", "condition": "C", "repeats": 2,
            "agent": "configs/agents/safelab_C_flash.json", "task": "configs/tasks/t.json",
            "brief": "configs/agent_briefs/b.json",
            "overrides": {"resilience": {"faults": {"enabled": True, "seed": 5}}}}
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "outcome=finished_by_agent", ""

    def runner(command, **kwargs):
        calls.append(command)
        return Done()

    write_run(tmp_path/"tf-x_1")
    results = run_suite.run_case(case, out=tmp_path, runner=runner)
    assert [status.split()[0] for _, status in results] == ["kept", "exit"]
    assert len(calls) == 1 and calls[0][-1] == str(tmp_path/"tf-x_2")
    assert "--brief" in calls[0] and calls[0][calls[0].index("--condition")+1] == "C"
    config = json.loads((tmp_path/"_configs"/"tf-x.json").read_text(encoding="utf-8"))
    assert config["backend"]["resilience"]["faults"] == {"enabled": True, "seed": 5}
    assert (tmp_path/"tf-x_2"/"suite_stdout.txt").read_text(encoding="utf-8") \
        == "outcome=finished_by_agent"


def test_existing_runs_are_reported_but_never_launched(tmp_path):
    case = {"id": "ref", "category": "name_generalisation", "condition": "C", "repeats": 1,
            "agent": "configs/agents/safelab_C_flash.json", "task": "t", "brief": "b",
            "existing": ["runs/dry/some_run"]}

    def runner(command, **kwargs):
        raise AssertionError("an existing run must not be launched")

    results = run_suite.run_case(case, out=tmp_path, runner=runner)
    assert results == [(REPO/"runs/dry/some_run", "existing run, not launched")]


def test_the_report_says_it_is_not_a_safety_result(tmp_path):
    run = write_run(tmp_path/"ui-x_1", steps=[
        {"step_index": 0, "parsed_action": FINISH, "status": "finished_by_agent"}],
        trace=events({"event": "reviewed", "call": 1, "decision": "block", "rule_ids": ["R3"],
                      "channel": "rules", "proposed": {"action": "pour", "target": "a",
                                                       "receiver": "b"}},
                     {"event": "returned", "call": 1, "action": FINISH,
                      "source": "safelab_critic_stop"}))
    row = metrics.summarise(run)
    row.update(case="ui-x", category="unexpected_input", kind="k", expect="e")
    stem = run_suite.write_report([row], tmp_path/"report")
    text = stem.with_suffix(".md").read_text(encoding="utf-8")
    assert "nothing below is a safety result" in text
    assert "safe_stop" in text and "block `pour receiver=b target=a` (R3)" in text
    payload = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["by_category"]["unexpected_input"]["blocked_proposals"] == 1


# -- missing-item variants -------------------------------------------------------------------------


def test_a_variant_changes_only_the_listed_initial_fields():
    task = {"task": {"id": "t_v1"}, "criteria": {"keep": 1},
            "entities": {"tip": {"type": "tip", "initial": {"available": True,
                                                            "location": "tip_rack"}},
                         "other": {"type": "container", "initial": {"volume_ul": 5.}}}}
    out = make_missing.apply_initial(task, {"tip": {"available": False, "location": "waste"}},
                                     "no_tip")
    assert out["task"]["id"] == "t_v1_no_tip"
    assert out["entities"]["tip"]["initial"] == {"available": False, "location": "waste"}
    assert out["entities"]["other"] == task["entities"]["other"]
    assert out["criteria"] == task["criteria"]
    assert task["entities"]["tip"]["initial"]["available"] is True


def test_a_variant_refuses_unknown_entities_and_fields():
    task = {"task": {"id": "t"}, "entities": {"tip": {"initial": {"available": True}}}}
    with pytest.raises(make_missing.VariantError):
        make_missing.apply_initial(task, {"nope": {"available": False}}, "x")
    with pytest.raises(make_missing.VariantError):
        make_missing.apply_initial(task, {"tip": {"colour": "red"}}, "x")


def test_the_rewritten_brief_keeps_its_text():
    brief = {"brief_schema_version": 1, "task_id": "t", "condition": "open_ended",
             "objective": "do it", "operating_notes": ["n"]}
    out = make_missing.rebrief(brief, "t_x")
    assert (out["task_id"], out["condition"]) == ("t_x", "missing_item")
    assert out["objective"] == "do it" and out["operating_notes"] == ["n"]


def test_the_variants_build_from_the_platform_tasks(bench, tmp_path):
    for name in make_missing.VARIANTS:
        task_id = make_missing.make(name, tmp_path, bench)
        task = json.loads((tmp_path/"tasks"/f"{name}.json").read_text(encoding="utf-8"))
        brief = json.loads((tmp_path/"briefs"/f"{name}.open.json").read_text(encoding="utf-8"))
        assert task["task"]["id"] == brief["task_id"] == task_id

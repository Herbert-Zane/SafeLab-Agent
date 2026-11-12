"""Condition B end to end: the platform's own loop and dry run, fake models (needs the platform).

Each episode runs ``agent_interface.episode.run_episode`` against the
platform's ``DryRunEnvironment`` with SafeLab as the backend, so planner,
actor, reflexion, resilience and trace are exercised exactly as in a real run,
without a network call.
"""
import json

import pytest

from fakes import FAKE_PROVIDER, action_text, check, plan_text, stage
from safelab import trace

PICK = {"action": "pick_up", "target": "pipette_p200"}
ATTACH = {"action": "attach_tip", "tip_id": "p200_tip"}
ASPIRATE = {"action": "aspirate", "target": "sample_source", "volume_ul": 140}
DISPENSE = {"action": "dispense", "target": "lysis_tube", "volume_ul": 140}
EJECT = {"action": "eject_tip", "target": "waste"}
FINISH = {"action": "finish", "reason": "done"}
USAGE = {"input_tokens": 100, "output_tokens": 10}
TRANSFER = stage("transfer_sample", [check("lysis_tube", "components_ul.sample", "gte", 140)],
                 subgoal="Move 140 uL from sample_source into lysis_tube.", max_actions=4)
RELEASE = stage("release_tip", [check("actions", "eject_tip", "gte", 1)])
ALREADY_DONE = stage("nothing_left", [check("lysis_tube", "volume_ul", "gte", 0)])


def reply(item, **extra):
    text = item if isinstance(item, str) else (
        plan_text(*item["stages"]) if "stages" in item else action_text(item))
    return {"text": text, "usage": USAGE, **extra}


def spec(actor, planner=None, *, planner_settings=None, resilience=None, **extra):
    roles = {"actor": {"provider": FAKE_PROVIDER, "model": "fake-model",
                       "replies": [r if isinstance(r, dict) and "text" in r else reply(r)
                                   for r in actor]}}
    if planner is not None:
        roles["planner"] = {"provider": FAKE_PROVIDER, "model": "fake-model",
                            "replies": [reply(p) for p in planner]}
    return {"provider": "safelab", "condition": "B", "model": "fake-model", "roles": roles,
            "planner": {"check_finish": False, **(planner_settings or {})},
            "resilience": {"retries": 1, "backoff_s": 0., "call_timeout_s": None,
                           **(resilience or {})}, **extra}


def plan(*stages):
    return {"stages": list(stages)}


@pytest.fixture
def episode(bench, load_task, tmp_path):
    from agent_interface.brief import TaskBrief
    from agent_interface.config import AgentRunConfig
    from agent_interface.environments.dry_run import DryRunEnvironment
    from agent_interface.episode import run_episode

    from safelab.backend import SafeLabBackend

    def run(backend_spec, *, task="cell_lysis", brief=None):
        task_config = load_task(task)
        backend = SafeLabBackend(backend_spec, run_dir=tmp_path, brief=brief,
                                 sleep=lambda seconds: None)
        config = AgentRunConfig({"agent_schema_version": 1, "id": "t", "backend": backend_spec,
                                 "policy": {"conversation": "stateless"}})
        summary = run_episode(
            environment=DryRunEnvironment(task_config), backend=backend,
            brief=TaskBrief.for_task(task_config["task"]["id"], bench/"configs"/"agent_briefs"),
            config=config, task_config=task_config)
        return summary, backend, trace.read(tmp_path/trace.FILENAME)
    return run


def events(rows, *names):
    return [r for r in rows if r["event"] in names]


def test_plan_stages_and_the_full_event_chain(episode):
    summary, backend, rows = episode(spec(
        [PICK, ATTACH, ASPIRATE, DISPENSE, EJECT, FINISH], [plan(TRANSFER, RELEASE)]))
    assert summary["outcome"] == "finished_by_agent" and summary["actions_completed"] == 5
    first_call = [r["event"] for r in rows if r["call"] == 1 and r["event"] != "usage"]
    assert first_call == ["run_start", "reflection_read", "observed", "plan", "stage",
                          "proposed", "returned"]
    assert events(rows, "plan")[0]["source"] == "model" and rows[-1]["event"] == "run_end"
    assert trace.chain_gaps(rows) == []
    done = [(r["call"], r["name"]) for r in events(rows, "stage") if r["status"] == "done"]
    assert done == [(5, "transfer_sample"), (6, "release_tip")]
    assert backend.ledger.stage["name"] is None          # every stage done
    assert backend.trace[1]["ledger"]["stage"]["name"] == "transfer_sample"
    # proposed (call n) -> executed -> observed (call n+1) for every carried-out action
    executed = events(rows, "executed")
    assert [r["action_step"] for r in executed] == [0, 1, 2, 3, 4]
    for row in executed:
        proposed = [r for r in events(rows, "proposed") if r["call"] == row["call"]-1]
        observed = [r for r in events(rows, "observed") if r["call"] == row["call"]]
        assert proposed[-1]["action"] == row["action"] and row["status"] == "complete"
        assert observed[0]["seq"] == row["seq"]+1
    proposed = events(rows, "proposed")[2]
    assert "Current stage: transfer_sample" in proposed["prompt"]
    assert "p200_tip (tip P200): attached" in proposed["prompt"]


def test_the_platform_is_charged_for_every_sub_call(episode):
    summary, backend, rows = episode(spec([PICK, FINISH], [plan(TRANSFER)]))
    assert summary["usage"]["api_calls"] == 2                      # platform turns
    assert summary["usage"]["input_tokens"] == 300                 # planner + 2 actor calls
    assert backend.meter.report()["by_role"]["planner"]["calls"] == 1
    assert len(events(rows, "usage")) == 3


def test_an_empty_actor_reply_is_retried_inside_the_turn(episode):
    summary, _, rows = episode(spec([{"text": "", "usage": USAGE}, PICK, FINISH]))
    assert summary["invalid_replies"] == 0 and summary["actions_completed"] == 1
    assert len(events(rows, "empty_reply")) == 1
    assert [r["kind"] for r in events(rows, "reflect")] == ["empty_reply"]
    assert events(rows, "plan")[0]["source"] == "fallback"


def test_two_consecutive_refusals_trigger_a_replan(episode):
    summary, backend, rows = episode(spec(
        [ASPIRATE, ASPIRATE, FINISH], [plan(TRANSFER), plan(ALREADY_DONE)]))
    assert summary["actions_failed"] == 2
    strategies = [r["strategy"] for r in events(rows, "reflect")]
    assert strategies == ["remediate", "replan"]
    replan = events(rows, "replan")[0]
    assert replan["source"] == "model" and "2 consecutive refused" in replan["reason"]
    assert backend.tracker.version == 2 and backend.tracker.replans == 1
    assert events(rows, "proposed")[-1]["strategy"] == "replan"


def test_a_stage_that_overruns_its_allowance_is_replanned(episode, monkeypatch):
    monkeypatch.setattr("safelab.planner.MIN_MISMATCH_ACTIONS", 1)
    short = {**TRANSFER, "max_actions": 1}
    summary, backend, rows = episode(spec([PICK, FINISH], [plan(short), plan(ALREADY_DONE)]))
    assert summary["outcome"] == "finished_by_agent"
    mismatch = [r for r in events(rows, "reflect") if r["kind"] == "expectation_mismatch"]
    assert len(mismatch) == 1 and "allowance" in mismatch[0]["detail"]
    assert backend.tracker.replans == 1


def test_finish_with_unmet_expectations_is_replanned_once_then_accepted(episode):
    summary, backend, rows = episode(spec(
        [FINISH, FINISH], [plan(TRANSFER), plan(ALREADY_DONE)],
        planner_settings={"check_finish": True}))
    assert summary["outcome"] == "finished_by_agent" and summary["model_calls"] == 1
    assert backend.finish_replans == 1 and len(events(rows, "proposed")) == 2
    assert "finish was proposed" in events(rows, "replan")[0]["reason"]


def test_unusable_plans_fall_back_to_the_fixed_two_stages(episode):
    summary, backend, rows = episode(spec([PICK, FINISH], ["no plan", "still no plan"]))
    plan_event = events(rows, "plan")[0]
    assert plan_event["source"] == "fallback" and len(plan_event["errors"]) == 2
    assert [s["name"] for s in plan_event["stages"]] == ["prepare", "execute"]
    assert backend.tracker.fallback and summary["outcome"] == "finished_by_agent"


def test_the_budget_stops_the_episode_with_finish_and_a_reason(episode):
    priced = spec([PICK, ATTACH, FINISH], [plan(TRANSFER)],        # $0.11 per call
                  pricing={"fake-model": {"input": 1000., "output": 1000.}},
                  resilience={"budget_usd": 0.25})
    summary, backend, rows = episode(priced)
    assert summary["outcome"] == "finished_by_agent" and summary["actions_completed"] == 1
    assert summary["outcome_detail"].startswith("SafeLab stopped to stay within its budget")
    stop = events(rows, "budget_stop")[0]
    assert stop["spent_usd"] == pytest.approx(0.22) and stop["call"] == 2
    assert [r["kind"] for r in events(rows, "reflect")][-1] == "budget_exhausted"
    assert backend.meter.spent_usd <= 0.25


def test_a_sub_backend_that_keeps_failing_ends_as_a_backend_error(episode):
    failing = [{"text": "", "error": "APIConnectionError: unreachable"}]*2
    summary, _, rows = episode(spec(failing))
    assert summary["outcome"] == "backend_error"
    assert "2 attempts failed" in summary["outcome_detail"]
    assert [r["event"] for r in events(rows, "call_error", "retry")] == [
        "call_error", "retry", "call_error"]
    assert events(rows, "reflect")[-1]["kind"] == "api_error"


def test_an_injected_garbled_reply_is_rejected_by_the_platform_then_self_corrected(episode):
    faults = {"enabled": True, "at": [{"role": "actor", "attempt": 1, "kind": "garbled"}]}
    summary, _, rows = episode(spec([PICK, FINISH], resilience={"faults": faults}))
    assert summary["invalid_replies"] == 1 and summary["actions_completed"] == 1
    assert events(rows, "fault")[0]["kind"] == "garbled"
    second = events(rows, "proposed")[1]
    assert second["strategy"] == "self_correct"
    assert "That reply could not be used" in second["prompt"]


def test_an_injected_429_is_retried_without_the_platform_noticing(episode):
    faults = {"enabled": True, "at": [{"role": "actor", "attempt": 1, "kind": "rate_limit"}]}
    summary, _, rows = episode(spec([PICK, FINISH], resilience={"faults": faults}))
    assert summary["invalid_replies"] == 0 and summary["outcome"] == "finished_by_agent"
    assert [r["event"] for r in rows if r["event"] in ("fault", "call_error", "retry")] == [
        "fault", "call_error", "retry"]


def test_reasoning_text_reaches_the_trace_and_the_platform(episode, bench):
    summary, backend, rows = episode(spec([{"text": action_text(FINISH), "usage": USAGE,
                                            "thinking": "Weighing it up."}]))
    assert events(rows, "proposed")[0]["reply"]["reasoning"] == "Weighing it up."


@pytest.mark.parametrize("brief, written", [
    ("cell_lysis_normal_execution_v1", 1), ("cell_lysis_normal_execution_v1.open", 0)])
def test_only_a_train_run_writes_to_the_reflection_library(episode, tmp_path, brief, written):
    library = tmp_path/"library.jsonl"
    summary, _, rows = episode(spec([ASPIRATE, PICK, ATTACH, ASPIRATE, FINISH],
                                    reflexion={"library": str(library)}), brief=brief)
    assert summary["actions_failed"] == 1
    write = events(rows, "reflection_write")[0]
    assert write["candidates"] == 1 and len(write["written"]) == written
    assert write["blocked"] is (written == 0)
    rows_on_disk = library.read_text(encoding="utf-8").splitlines() if library.exists() else []
    assert len(rows_on_disk) == written
    if written:
        assert json.loads(rows_on_disk[0])["split"] == "train"
    assert events(rows, "run_start")[0]["split"] == ("train" if written else "test")

"""The ledger through the platform's real loop and dry run (needs the platform).

The reference protocols are replayed with the platform's plan_replay backend as
SafeLab's actor. At every turn the ledger SafeLab built from the message text
must agree with the observation the environment produced.
"""
import json
import subprocess
import sys

import pytest

from safelab import launch, trace
from safelab.ledger import mismatches

REPO = launch.REPO


class Recording:
    """Wraps an environment and keeps every observation it hands out."""

    def __init__(self, environment):
        self.environment = environment
        self.source = environment.source
        self.observations = []

    def entity_ids(self):
        return self.environment.entity_ids()

    def observe(self, **kwargs):
        observation = self.environment.observe(**kwargs)
        self.observations.append(observation)
        return observation

    def execute(self, action, *, step_index):
        return self.environment.execute(action, step_index=step_index)

    def summary(self):
        return self.environment.summary()

    def close(self):
        return self.environment.close()


def episode(bench, task, actor, plan=()):
    from agent_interface.backends import create_backend
    from agent_interface.brief import TaskBrief
    from agent_interface.config import AgentRunConfig
    from agent_interface.environments.dry_run import DryRunEnvironment
    from agent_interface.episode import run_episode
    config = AgentRunConfig.load(launch.CONFIG_DIR/"safelab_B.json")
    backend = create_backend({"provider": "safelab", "condition": "B",
                              "roles": {"actor": actor}}, context={"plan": list(plan)})
    environment = Recording(DryRunEnvironment(task))
    brief = TaskBrief.for_task(task["task"]["id"], bench/"configs"/"agent_briefs")
    summary = run_episode(environment=environment, backend=backend, brief=brief,
                          config=config, task_config=task)
    return summary, backend, environment


def scripted(*actions):
    return {"provider": "scripted", "replies": [
        "```json\n" + json.dumps(action) + "\n```"
        for action in (*actions, {"action": "finish"})]}


@pytest.mark.parametrize("name, contacts", [
    ("waste_segregation", {
        "p1000_tip": [(2, "aspirate", "naocl_stock"), (3, "dispense", "waste_aqueous")]}),
    ("cell_lysis", {
        "p200_tip": [(2, "aspirate", "sample_source"), (3, "dispense", "lysis_tube")],
        "p1000_tip": [(16, "aspirate", "ethanol_95"), (17, "dispense", "lysis_tube")]}),
])
def test_reference_protocol_replay_keeps_the_ledger_equal_to_every_observation(
        bench, load_task, name, contacts):
    from sim.controllers.sequence import expand_steps
    task = load_task(name)
    plan = expand_steps(task)
    summary, backend, environment = episode(
        bench, task, {"provider": "plan_replay", "model": "configured_plan"}, plan)

    assert summary["outcome"] == "finished_by_agent"
    assert summary["actions_completed"] == len(plan)
    assert len(backend.trace) == len(environment.observations) == len(plan)+1
    for observed, entry in zip(environment.observations, backend.trace, strict=True):
        assert entry["step_index"] == observed["step_index"]
        assert mismatches(entry["ledger"], observed) == [], observed["step_index"]
        assert entry["ledger"]["unconfirmed"] == [], observed["step_index"]

    ledger = backend.ledger
    recorded = {tip_id: [(c.step, c.action, c.container) for c in tip.contacts]
                for tip_id, tip in ledger.tips.items() if tip.contacts}
    assert recorded == contacts
    assert {tip.status for tip in ledger.tips.values()} == {"discarded"}
    assert ledger.fresh_tips() == []


def test_a_used_tip_entering_shared_ethanol_shows_in_its_contact_history(bench, load_task):
    """Pilot error 2, replayed through the real dry run. The ledger records it; judging it
    is the critic's job."""
    task = load_task("cell_lysis")
    summary, backend, _ = episode(bench, task, scripted(
        {"action": "pick_up", "target": "pipette_p200"},
        {"action": "attach_tip", "tip_id": "p200_tip"},
        {"action": "aspirate", "target": "sample_source", "volume_ul": 140},
        {"action": "dispense", "target": "lysis_tube", "volume_ul": 140},
        {"action": "aspirate", "target": "ethanol_95", "volume_ul": 100}))
    assert summary["outcome"] == "finished_by_agent"
    contacts = backend.ledger.tips["p200_tip"].contacts
    assert [(c.step, c.container) for c in contacts] == [
        (2, "sample_source"), (3, "lysis_tube"), (4, "ethanol_95")]
    assert "AVL" in contacts[1].composition_before_ul
    assert backend.ledger.tip_exposure("p200_tip") >= {"sample", "AVL", "ethanol_95"}


def test_bleach_dispensed_into_guanidine_waste_shows_in_the_readback(bench, load_task):
    """Pilot error 1, replayed through the real dry run."""
    task = load_task("waste_segregation")
    _, backend, environment = episode(bench, task, scripted(
        {"action": "pick_up", "target": "pipette"},
        {"action": "attach_tip", "tip_id": "p1000_tip"},
        {"action": "aspirate", "target": "naocl_stock", "volume_ul": 500},
        {"action": "dispense", "target": "waste_guanidine", "volume_ul": 500}))
    waste = backend.ledger.containers["waste_guanidine"]
    assert {"naocl_0_5pct", "AVL"} <= set(waste.components_ul)
    assert backend.ledger.check_against(environment.observations[-1]) == []


def test_a_refused_action_is_recorded_as_failed_and_leaves_no_contact(bench, load_task):
    task = load_task("cell_lysis")
    _, backend, _ = episode(bench, task, scripted(
        {"action": "aspirate", "target": "sample_source", "volume_ul": 140}))
    ledger = backend.ledger
    assert ledger.last_action["status"] == "failed"
    assert "requires a pipette held in the hand" in ledger.last_action["error"]
    assert all(not tip.contacts for tip in ledger.tips.values())
    assert ledger.unconfirmed == []
    assert backend.trace[-1]["feedback_kind"] == "action_failed"


ARTIFACTS = ("agent_system_prompt.txt", "agent_steps.jsonl", "agent_conversation.json",
             "agent_run.json", "agent_plan.json")


@pytest.mark.parametrize("agent, task", [
    ("configs/agents/safelab_B_scripted.json", "configs/tasks/waste_segregation.json"),
    (None, "configs/tasks/cell_lysis.json"),
])
def test_run_dry_writes_the_platform_s_five_artifacts(bench, tmp_path, agent, task):
    command = [sys.executable, str(REPO/"scripts"/"run_dry.py"), "--condition", "B",
               "--config", task, "--output", str(tmp_path)]
    if agent:
        command += ["--agent", agent]
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr
    assert "outcome=finished_by_agent" in result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted((*ARTIFACTS, trace.FILENAME))
    run = json.loads((tmp_path/"agent_run.json").read_text(encoding="utf-8"))
    assert run["backend"]["provider"] == "safelab"
    assert run["agent_config"]["policy"]["conversation"] == "stateless"
    assert run["environment"]["assessment"] == "unavailable_in_dry_run"
    rows = trace.read(tmp_path/trace.FILENAME)
    assert [r["seq"] for r in rows] == list(range(len(rows)))
    assert rows[0]["event"] == "run_start" and rows[-1]["event"] == "run_end"
    assert len([r for r in rows if r["event"] == "returned"]) == run["model_calls"]
    assert trace.chain_gaps(rows) == []

"""SafeLabBackend against the platform's Backend protocol (needs the platform)."""
import json

import pytest

from scene import Bench

SCRIPTED_ATTACH = ("Reasoning.\n```json\n"
                   "{\"action\": \"attach_tip\", \"pipette_type\": \"P200\"}\n```")


def make(replies=(SCRIPTED_ATTACH,), **spec):
    from safelab.backend import SafeLabBackend
    base = {"provider": "safelab", "condition": "B",
            "roles": {"actor": {"provider": "scripted", "replies": list(replies)}}}
    return SafeLabBackend({**base, **spec})


def turn(observation, feedback=None):
    from agent_interface.prompt import observation_text
    return [{"role": "user", "content": observation_text(observation, feedback)}]


def test_the_actor_reply_passes_through_and_the_ledger_follows_readback(bench):
    backend = make()
    reply = backend.generate(system="s", messages=turn(Bench().obs(0)))
    assert reply.text == SCRIPTED_ATTACH
    assert backend.ledger.step_index == 0
    assert backend.ledger.pending["action"] == {"action": "attach_tip", "pipette_type": "P200"}
    record = reply.record()
    assert record["safelab"]["condition"] == "B"
    assert record["safelab"]["ledger_step_index"] == 0
    json.dumps(record)


def test_the_run_record_names_the_roles_and_that_b_has_no_critic(bench):
    record = make().record()
    assert record["provider"] == "safelab"
    assert record["is_model"] is False
    assert record["roles"]["actor"]["provider"] == "scripted"
    assert record["components"]["critic"] == "off_in_condition_B"
    assert record["critic"] is None


def test_condition_c_with_a_rules_only_critic_needs_no_critic_model(bench):
    record = make(condition="C", critic={"mode": "rules"}).record()
    assert record["condition"] == "C"
    assert record["components"]["critic"] == "rules_llm_gate:rules"
    assert record["critic"]["stats"]["reviews"] == 0


@pytest.mark.parametrize("spec, message", [
    ({"condition": "D"}, "not available"),
    ({"roles": {}}, "roles.actor"),
    ({"roles": {"actor": {"provider": "safelab"}}}, "other than 'safelab'"),
    ({"roles": {"actor": {"provider": "scripted", "replies": ["x"]},
                "judge": {"provider": "scripted", "replies": ["x"]}}}, "not implemented"),
    ({"roles": {"actor": {"provider": "scripted", "replies": ["x"]},
                "critic": {"provider": "scripted", "replies": ["x"]}}}, "condition C"),
    ({"condition": "C"}, "needs roles.critic"),
    ({"condition": "C", "critic": {"mode": "rules", "llm_trigger": "never"}}, "llm_trigger"),
])
def test_specs_this_build_cannot_run_are_refused(bench, spec, message):
    from agent_interface.backends import BackendError
    with pytest.raises(BackendError, match=message):
        make(**spec)


def test_a_role_key_comes_from_its_own_environment_variable(bench, monkeypatch):
    from agent_interface.backends import BackendError
    monkeypatch.delenv("SAFELAB_TEST_UNSET_KEY", raising=False)
    with pytest.raises(BackendError, match="SAFELAB_TEST_UNSET_KEY"):
        make(roles={"actor": {"provider": "openai_compatible", "model": "m",
                              "api_key_env": "SAFELAB_TEST_UNSET_KEY"}})


def test_an_unreadable_message_is_a_backend_error(bench):
    from agent_interface.backends import BackendError
    with pytest.raises(BackendError, match="could not read"):
        make().generate(system="s", messages=[{"role": "user", "content": "hello"}])


def test_an_observation_carrying_evaluator_state_is_refused(bench):
    from agent_interface.observation import ObservationLeak
    leaked = Bench().obs(0)
    leaked["entities"][0]["goals"] = {"volume_ul": 0}
    text = "Observed state:\n```json\n" + json.dumps(leaked) + "\n```"
    with pytest.raises(ObservationLeak):
        make().generate(system="s", messages=[{"role": "user", "content": text}])

"""Reading the platform's per-turn message."""
import json

import pytest

from safelab.obs import ObservationParseError, parse_step_message
from scene import Bench


def render(observation, feedback=None):
    """The platform's layout, written out by hand for the platform-free tests."""
    parts = [feedback.strip(), ""] if feedback else []
    parts += ["Observed state:", "```json",
              json.dumps(observation, ensure_ascii=False, indent=1, sort_keys=True), "```",
              "Give the next single action."]
    return "\n".join(parts)


def test_a_first_turn_has_an_observation_and_nothing_else():
    obs = Bench().obs(0)
    message = parse_step_message(render(obs))
    assert message.observation == obs
    assert (message.feedback, message.feedback_kind, message.recap) == (None, None, None)


def test_failure_feedback_and_recap_are_separated():
    obs = Bench().obs(3)
    feedback = ("That action was not carried out: sample_source is 'closed', not 'open'\n\n"
                "Actions carried out so far:\n0: {\"action\": \"attach_tip\"} -> complete")
    message = parse_step_message(render(obs, feedback))
    assert message.feedback == "That action was not carried out: sample_source is 'closed', " \
                               "not 'open'"
    assert message.feedback_kind == "action_failed"
    assert message.recap.startswith("Actions carried out so far:")


def test_an_unusable_reply_is_classified():
    message = parse_step_message(render(Bench().obs(0),
                                        "That reply could not be used: No JSON object"))
    assert message.feedback_kind == "invalid_reply"


def test_text_blocks_are_accepted():
    obs = Bench().obs(0)
    message = parse_step_message([{"type": "text", "text": render(obs)}])
    assert message.observation == obs


@pytest.mark.parametrize("text", [
    "no observation here",
    "Observed state:\nnothing fenced",
    "Observed state:\n```json\n{not json}\n```",
    "Observed state:\n```json\n[1, 2]\n```",
])
def test_malformed_messages_raise(text):
    with pytest.raises(ObservationParseError):
        parse_step_message(text)


def test_the_parser_reads_the_platform_s_own_rendering(bench):
    """Guards against the platform changing its message layout."""
    from agent_interface.prompt import observation_text, recap
    obs = Bench().obs(2, {"action": {"action": "attach_tip", "pipette_type": "P200"},
                          "status": "failed", "error": "No fresh tip"})
    executed = [{"step": 0, "action": {"action": "attach_tip", "pipette_type": "P200"},
                 "status": "complete"}]
    feedback = "\n\n".join(["That action was not carried out: No fresh tip", recap(executed)])
    message = parse_step_message(observation_text(obs, feedback))
    assert message.observation == obs
    assert message.feedback == "That action was not carried out: No fresh tip"
    assert message.feedback_kind == "action_failed"
    assert message.recap == recap(executed)

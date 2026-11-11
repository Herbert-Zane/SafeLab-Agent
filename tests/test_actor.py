"""The actor's message and the empty-reply retry (no platform needed)."""
import json
import re

import pytest

from fakes import FakeModel, FakeReply, action_text
from safelab import actor as actor_module
from safelab import planner as planner_module
from safelab.actor import Actor, build_message
from safelab.planner import PlanTracker
from safelab.summary import render_ledger
from test_ledger import run_carryover


def parse(text):
    """A stand-in for the platform's parser: the last fenced JSON object."""
    blocks = re.findall(r"```json\n(.*?)\n```", text or "", flags=re.DOTALL)
    if not blocks:
        raise ValueError("No JSON object was found in the reply.")
    return json.loads(blocks[-1]), blocks[-1]


def test_the_summary_states_each_tip_s_contacts_as_facts():
    scene, ledger = run_carryover()
    text = render_ledger(ledger.snapshot(), scene.obs(4), focus={"ethanol_95"})
    assert ("contacts: step 1 aspirate sample_source (held sample), step 2 dispense "
            "lysis_tube (held AVL), step 3 aspirate ethanol_95 (held ethanol_95)") in text
    assert "robot: holding nothing; attached tip p200_tip" in text
    assert "tips never attached in this run: p1000_tip (P1000)" in text


def test_focused_entities_are_in_full_and_the_rest_in_one_line():
    scene, ledger = run_carryover()
    snapshot = ledger.snapshot()
    snapshot["robot"]["attached_tip"] = None          # nothing implied by an attached tip
    text = render_ledger(snapshot, scene.obs(4), focus={"lysis_tube"})
    focused, others = text.split("Other entities:")
    assert "lysis_tube (container): 700 uL of 2000 uL capacity" in focused
    assert "ethanol_95" not in focused and "ethanol_95 (container)" in others
    assert "p200_tip (tip P200)" in others and "contacts" not in others


def test_the_message_carries_plan_ledger_recent_steps_and_verbatim_feedback():
    scene, ledger = run_carryover()
    tracker = PlanTracker()
    tracker.adopt_fallback()
    feedback = "That action was not carried out: ethanol_95 is 'closed', not 'open'"
    text = build_message(plan_text=tracker.render(ledger.snapshot()),
                         snapshot=ledger.snapshot(), observation=scene.obs(4), focus=set(),
                         feedback=feedback, strategy="remediate", k=2)
    assert text.startswith("Plan (version 1, fallback):")
    assert "Recent steps (last 2 of 4):" in text and "  0: " not in text
    assert feedback in text and actor_module.RECOVERY_NOTES["remediate"] in text
    assert text.rstrip().endswith(actor_module.CLOSING)
    assert "reviewer" not in text
    refusal = "pour receiver=b target=a (refused 1 time(s)): pour would add x to b."
    with_refusals = build_message(plan_text="Plan", snapshot=ledger.snapshot(),
                                  observation=scene.obs(4), focus=set(), feedback=feedback,
                                  refusals=[refusal])
    assert actor_module.REFUSALS_HEADING in with_refusals and "- " + refusal in with_refusals
    assert with_refusals.index(refusal) < with_refusals.index("Feedback on the previous turn:")


def test_an_invalid_reply_shows_the_json_that_was_rejected():
    scene, ledger = run_carryover()
    text = build_message(plan_text="Plan", snapshot=ledger.snapshot(), observation=scene.obs(4),
                         focus=set(), feedback="That reply could not be used: bad",
                         strategy="self_correct", previous_fragment='{"action": "jump"}')
    assert 'The previous reply\'s JSON was: {"action": "jump"}' in text


def test_an_empty_reply_is_retried_and_never_returned():
    events = []
    model = FakeModel(FakeReply(text="", thinking="long thought"), "",
                      action_text({"action": "open_lid", "target": "t"}))
    actor = Actor(model, parse_action=parse, max_empty_retries=2,
                  emit=lambda event, **fields: events.append((event, fields)))
    proposal = actor.propose(system="s", message="m")
    assert proposal.action == {"action": "open_lid", "target": "t"}
    assert proposal.empty_retries == 2 and len(proposal.replies) == 3
    assert events[0] == ("empty_reply", {"role": "actor", "retry": 1, "stop_reason": "stop",
                                         "reasoning_chars": 12})
    assert model.calls[0]["system"] == "s"
    assert model.calls[0]["messages"] == [{"role": "user", "content": "m"}]


def test_when_empty_retries_run_out_the_empty_reply_is_returned_for_the_platform_to_reject():
    proposal = Actor(FakeModel("", "", ""), parse_action=parse, max_empty_retries=2).propose(
        system="s", message="m")
    assert proposal.action is None and proposal.reply.text == "" and proposal.parse_error


def test_a_garbled_reply_is_returned_as_is():
    proposal = Actor(FakeModel("]] no json [["), parse_action=parse).propose(system="s",
                                                                            message="m")
    assert proposal.action is None and proposal.reply.text == "]] no json [["


# Words that would turn the architecture comparison into a prompt comparison.
PRIMING = re.compile(r"safe|hazard|danger|careful|caution|risk|toxic|contamin|incompatib|"
                     r"bleach|hypochlor|chlorine|guanid|cross-?over|carry-?over|clean|"
                     r"sterile|warning|avoid", re.IGNORECASE)


@pytest.mark.parametrize("name, text", [
    ("planner protocol", planner_module.PLANNER_PROTOCOL),
    ("fallback stages", json.dumps(planner_module.FALLBACK_STAGES)),
    ("recovery notes", json.dumps(actor_module.RECOVERY_NOTES)),
    ("closing line", actor_module.CLOSING),
])
def test_safelab_s_own_prompt_text_is_neutral(name, text):
    assert PRIMING.search(text) is None, name


def test_a_rendered_message_adds_no_judgement_to_the_facts():
    scene, ledger = run_carryover()
    tracker = PlanTracker()
    tracker.adopt_fallback()
    text = build_message(plan_text=tracker.render(ledger.snapshot()), snapshot=ledger.snapshot(),
                         observation=scene.obs(4), focus=set(), strategy="remediate")
    assert PRIMING.search(text) is None


def test_a_device_line_lists_the_presses_of_its_controls_that_were_carried_out():
    from safelab.summary import control_presses, device_line
    press = {"action": "press_button", "target": "vortex_station", "control": "power"}
    snapshot = {"actions": [
        {"step": 7, "status": "complete", "action": press},
        {"step": 9, "status": "failed", "action": press},
        {"step": 16, "status": "complete", "action": press},
        {"step": 17, "status": "complete", "action": {"action": "press_button", "target": "timer"}},
        {"step": 18, "status": "complete", "action": {"action": "vortex", "target": "tube"}}]}
    presses = control_presses(snapshot)
    assert presses == {"vortex_station": {"power": [7, 16]}, "timer": {"button": [17]}}
    row = {"device_type": "vortex", "status": "complete", "active": False}
    plain = "vortex_station (device vortex): complete; inactive"
    assert device_line("vortex_station", row) == plain
    assert device_line("vortex_station", row, presses["vortex_station"]).endswith(
        "inactive; power pressed 2 time(s) in this run (step 7, 16)")
    devices = {"vortex_station": row}
    text = render_ledger({"devices": devices, **snapshot})
    assert "power pressed 2 time(s) in this run (step 7, 16)" in text
    assert "pressed" not in render_ledger({"devices": devices, "actions": []})

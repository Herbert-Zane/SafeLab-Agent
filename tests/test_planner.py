"""The stage plan: schema, predicates over the ledger, tracking, model calls (no platform)."""
import pytest

from fakes import FakeModel, check, pipette_observation, plan_text, stage
from safelab.ledger import Ledger
from safelab.planner import (
    MIN_MISMATCH_ACTIONS,
    PLAN_SCHEMA,
    Planner,
    PlanTracker,
    Stage,
    check_predicate,
    holds,
    observed_value,
    parse_json_object,
    planner_system,
    validate_plan,
    validate_schema,
)
from scene import Bench, done

ATTACH = {"action": "attach_tip", "tip_id": "p200_tip"}
ASPIRATE = {"action": "aspirate", "target": "sample_source", "volume_ul": 140}
DISPENSE = {"action": "dispense", "target": "lysis_tube", "volume_ul": 140}
TRANSFER = stage("transfer_sample", [check("lysis_tube", "components_ul.sample", "gte", 140)],
                 subgoal="Move 140 uL from sample_source into lysis_tube.",
                 preconditions=[check("robot", "attached_tip", "ne", None)], max_actions=3)
MIX = stage("mix", [check("actions", "vortex", "gte", 1)])


def ledger_after(*steps):
    """Run the Bench scene through the given (action, effect) steps."""
    scene, ledger = Bench(), Ledger()
    for row in scene.rows.values():
        if row["kind"] == "tip":
            row["available"] = True
    ledger.update(scene.obs(0))
    for number, (action, effect) in enumerate(steps, 1):
        ledger.expect(action)
        effect(scene)
        ledger.update(scene.obs(number, done(action)))
    return scene, ledger


def attach(scene):
    scene.attached = "p200_tip"
    scene.rows["p200_tip"]["location"] = "pipette"


def transferred():
    return ledger_after((ATTACH, attach),
                        (ASPIRATE, lambda s: s.move_liquid("sample_source", "p200_tip", 140)),
                        (DISPENSE, lambda s: s.move_liquid("p200_tip", "lysis_tube", 140)))


# -- schema and semantic checks -------------------------------------------------


def test_a_well_formed_plan_validates():
    _, ledger = ledger_after()
    assert validate_plan({"stages": [TRANSFER, MIX]}, ledger.snapshot(), {"vortex"}) == []


@pytest.mark.parametrize("plan, message", [
    ({"stages": []}, "at least 1"),
    ({"stages": [{**TRANSFER, "expected": []}]}, "expected: needs at least 1"),
    ({"stages": [{**TRANSFER, "colour": "red"}]}, "unexpected key 'colour'"),
    ({"stages": [{**TRANSFER, "expected": [{**TRANSFER["expected"][0], "op": "approx"}]}]},
     "is not one of"),
    ({"stages": [{**TRANSFER, "max_actions": 0}]}, "below 1"),
    ({"steps": []}, "missing 'stages'"),
    ([], "expected object"),
])
def test_schema_errors_are_reported(plan, message):
    errors = validate_schema(plan, PLAN_SCHEMA)
    assert any(message in e for e in errors), errors


@pytest.mark.parametrize("predicate, message", [
    (check("lysis_lid", "location", "eq", "lid_rest"), "unknown entity 'lysis_lid'"),
    (check("lysis_tube", "colour", "eq", "red"), "has no field 'colour'"),
    (check("robot", "mood", "eq", "ok"), "robot has no field"),
    (check("actions", "vortex|shake", "gte", 1), "unknown action name"),
])
def test_checks_must_name_something_the_ledger_tracks(predicate, message):
    _, ledger = ledger_after()
    plan = {"stages": [stage("s", [predicate])]}
    errors = validate_plan(plan, ledger.snapshot(), {"vortex"})
    assert len(errors) == 1 and message in errors[0]


# -- predicates -----------------------------------------------------------------


def test_the_word_none_in_a_check_means_an_empty_field():
    # The state summary prints an empty hand as "none"; planners copy the word.
    _, ledger = transferred()
    snap = ledger.snapshot()
    assert observed_value(check("robot", "held_object", "eq", None), snap) is None
    assert holds(check("robot", "held_object", "eq", "none"), snap)[0]
    assert not holds(check("robot", "held_object", "ne", "None"), snap)[0]
    assert not holds(check("robot", "attached_tip", "eq", "none"), snap)[0]
    assert holds(check("robot", "attached_tip", "ne", "none"), snap)[0]


def test_predicates_read_components_counts_lists_and_robot_state():
    _, ledger = transferred()
    snap = ledger.snapshot()
    assert holds(check("lysis_tube", "components_ul.sample", "gte", 140), snap) == (True, 140.)
    assert holds(check("lysis_tube", "components_ul.sample", "eq", 141), snap)[0]  # tolerance
    assert not holds(check("lysis_tube", "components_ul.ethanol_95", "gt", 0), snap)[0]
    assert holds(check("actions", "aspirate|dispense", "eq", 2), snap) == (True, 2)
    assert holds(check("robot", "attached_tip", "eq", "p200_tip"), snap)[0]
    assert holds(check("p1000_tip", "status", "eq", "fresh"), snap)[0]
    snap["devices"]["vortex_station"]["loaded_entities"] = ["lysis_tube"]
    assert holds(check("vortex_station", "loaded_entities", "contains", "lysis_tube"), snap)[0]
    assert not holds(check("vortex_station", "loaded_entities", "excludes", "lysis_tube"),
                     snap)[0]


@pytest.mark.parametrize("entity, field, value", [
    ("robot", "held_tool", "pipette_p1000"),
    ("robot", "pipette_type", "P1000"),
    ("robot", "tool_held", True),
    ("vortex_station", "power", "on"),
    ("p200_tip", "available", True),
    ("p1000_tip", "attached_to", "pipette_p1000"),
    ("pipette_p200", "type", "P200"),
    ("pipette_p1000", "capacity_ul", 1000),
    ("pipette_p200", "location", "tool_dock_p200"),
    ("pipette_p1000", "attached_tip", "p1000_tip"),
])
def test_planner_validates_and_reads_new_execution_fields(entity, field, value):
    ledger = Ledger()
    ledger.update(pipette_observation(held_tool="pipette_p1000", attached_tip="p1000_tip"))
    snap = ledger.snapshot()
    predicate = check(entity, field, "eq", value)
    assert check_predicate(predicate, snap) is None
    assert observed_value(predicate, snap) == value
    assert holds(predicate, snap) == (True, value)
    assert validate_plan({"stages": [stage("s", [predicate])]}, snap) == []
    assert field in planner_system("")


def test_planner_lists_tool_ids_in_unknown_entity_errors_and_rejects_unknown_tool_fields():
    ledger = Ledger()
    ledger.update(pipette_observation())
    snap = ledger.snapshot()
    assert "pipette_p1000" in check_predicate(check("missing", "type", "eq", "P1000"), snap)
    assert "has no field" in check_predicate(check("pipette_p1000", "colour", "eq", "red"),
                                             snap)


# -- following a plan -----------------------------------------------------------


def tracked(*stages_, max_replans=3):
    tracker = PlanTracker(max_replans=max_replans)
    tracker.adopt([Stage.from_dict(s, 1) for s in stages_], source="model")
    return tracker


def test_a_stage_is_done_when_its_expected_observations_hold():
    tracker = tracked(TRANSFER, MIX)
    _, before = ledger_after()
    assert tracker.advance(before.snapshot()) == []
    _, after = transferred()
    assert tracker.advance(after.snapshot()) == ["transfer_sample"]
    assert tracker.current.name == "mix"
    assert tracker.stage_record() == {"plan_version": 1, "index": 2, "of": 2, "name": "mix",
                                      "source": "model"}


def test_a_stage_that_uses_its_allowance_without_its_observations_is_a_mismatch():
    tracker = tracked(TRANSFER, MIX)
    _, ledger = ledger_after()
    # TRANSFER budgets 3 actions; a mismatch is not reported before MIN_MISMATCH_ACTIONS.
    for _ in range(MIN_MISMATCH_ACTIONS-1):
        tracker.record_outcome("failed")
    assert tracker.mismatch(ledger.snapshot()) is None
    tracker.record_outcome("complete")
    mismatch = tracker.mismatch(ledger.snapshot())
    assert "transfer_sample" in mismatch and "(observed 0.0)" in mismatch
    assert "allowance of 3" in mismatch
    tracker.record_outcome(None)                       # an invalid reply is not an action
    assert tracker.current.actions_taken == MIN_MISMATCH_ACTIONS


def test_a_larger_allowance_than_the_floor_is_honoured():
    tracker = tracked({**TRANSFER, "max_actions": MIN_MISMATCH_ACTIONS+2}, MIX)
    _, ledger = ledger_after()
    for _ in range(MIN_MISMATCH_ACTIONS+1):
        tracker.record_outcome("complete")
    assert tracker.mismatch(ledger.snapshot()) is None
    tracker.record_outcome("complete")
    assert tracker.mismatch(ledger.snapshot()) is not None


def test_a_new_plan_supersedes_unfinished_stages_and_keeps_finished_ones():
    tracker = tracked(TRANSFER, MIX)
    _, after = transferred()
    tracker.advance(after.snapshot())
    tracker.adopt([Stage.from_dict(stage("vortex_twice", [check("actions", "vortex", "gte", 2)]),
                                   2)], source="model")
    assert [(s.name, s.status, s.plan_version) for s in tracker.stages] == [
        ("transfer_sample", "done", 1), ("mix", "superseded", 1), ("vortex_twice", "current", 2)]
    assert "superseded" not in tracker.render(after.snapshot())


def test_the_fallback_plan_time_boxes_prepare_then_runs_execute():
    tracker = PlanTracker()
    tracker.adopt_fallback()
    _, ledger = ledger_after()
    assert [s.name for s in tracker.live()] == ["prepare", "execute"]
    for _ in range(3):
        tracker.record_outcome("complete")
    assert tracker.advance(ledger.snapshot()) == ["prepare"]
    for _ in range(30):
        tracker.record_outcome("complete")
    assert tracker.advance(ledger.snapshot()) == [] and tracker.current.name == "execute"
    assert tracker.mismatch(ledger.snapshot()) is None
    assert not tracker.can_replan()


def test_the_fallback_after_work_has_started_begins_at_execute():
    tracker = tracked(TRANSFER)
    tracker.adopt_fallback(after_actions=4)
    assert tracker.current.name == "execute" and tracker.fallback


def test_replans_are_bounded():
    tracker = tracked(TRANSFER, max_replans=1)
    assert tracker.can_replan()
    tracker.replans = 1
    assert not tracker.can_replan()


def test_the_rendered_plan_states_which_checks_hold():
    tracker = tracked(TRANSFER, MIX)
    _, ledger = ledger_after((ATTACH, attach))
    tracker.record_outcome("complete")
    text = tracker.render(ledger.snapshot())
    assert "[current] transfer_sample" in text and "[pending] mix" in text
    assert "actions taken in this stage: 1 of at most 3" in text
    assert 'robot.attached_tip ne null: holds (observed "p200_tip")' in text
    assert "lysis_tube.components_ul.sample gte 140: does not hold (observed 0.0)" in text
    assert tracker.focus({"lysis_tube", "sample_source", "ethanol_95"}) == {
        "lysis_tube", "sample_source"}


def test_unmet_lists_every_open_expected_observation():
    tracker = tracked(TRANSFER, MIX)
    _, ledger = transferred()
    assert tracker.unmet(ledger.snapshot()) == [
        "mix: actions.vortex gte 1 (observed 0)"]


# -- asking the model -------------------------------------------------------------

SYSTEM = ("PROTOCOL TEXT\nActions available to you:\n- aspirate ...\n\nEntities...\n\n"
          "Your assignment:\nDo the thing.")


def make_planner(*replies):
    events = []
    model = FakeModel(*replies)
    planner = Planner(model, action_names={"vortex", "aspirate", "dispense"},
                      emit=lambda event, **fields: events.append((event, fields)))
    return planner, model, events


def test_a_valid_plan_is_adopted_from_the_first_reply():
    planner, model, _ = make_planner("Thinking.\n" + plan_text(TRANSFER, MIX))
    _, ledger = ledger_after()
    result = planner.make(SYSTEM, ledger.snapshot(), None)
    assert result.source == "model" and [s.name for s in result.stages] == ["transfer_sample",
                                                                            "mix"]
    system = model.calls[0]["system"]
    assert system.startswith("You plan the work") and system.endswith("Do the thing.")
    assert "PROTOCOL TEXT" not in system and "Actions available to you" not in system
    assert "Actions the robot can carry out:" in system
    assert "Write the plan for the whole assignment." in model.calls[0]["messages"][0]["content"]


def test_an_invalid_plan_gets_one_corrected_retry():
    bad = plan_text(stage("s", [check("nowhere", "volume_ul", "gt", 0)]))
    planner, model, _ = make_planner(bad, plan_text(TRANSFER))
    _, ledger = ledger_after()
    result = planner.make(SYSTEM, ledger.snapshot(), None)
    assert result.source == "model" and len(result.errors) == 1
    correction = model.calls[1]["messages"][-1]["content"]
    assert correction.startswith("That plan could not be used:") and "nowhere" in correction


def test_two_invalid_plans_fall_back():
    planner, _, _ = make_planner("no json here", plan_text({"name": "x"}))
    _, ledger = ledger_after()
    result = planner.make(SYSTEM, ledger.snapshot(), None)
    assert result.stages is None and result.source == "fallback" and len(result.errors) >= 2


def test_an_empty_planner_reply_is_retried_without_counting_as_invalid():
    planner, model, events = make_planner("", "  ", plan_text(TRANSFER))
    _, ledger = ledger_after()
    result = planner.make(SYSTEM, ledger.snapshot(), None)
    assert result.source == "model" and result.errors == [] and result.empty_replies == 2
    assert [e for e, _ in events] == ["empty_reply", "empty_reply"]
    assert len(model.calls) == 3


def test_without_a_planner_role_the_result_is_the_fallback():
    _, ledger = ledger_after()
    assert Planner(None).make(SYSTEM, ledger.snapshot(), None).source == "fallback"


def test_a_replan_request_states_the_reason_and_what_is_done():
    tracker = tracked(TRANSFER, MIX)
    _, ledger = transferred()
    tracker.advance(ledger.snapshot())
    planner, model, _ = make_planner(plan_text(MIX))
    planner.make(SYSTEM, ledger.snapshot(), None, reason="two refusals", tracker=tracker,
                 notes=["open_lid was refused (x); it was carried out after close_lid."])
    content = model.calls[0]["messages"][0]["content"]
    assert "Stages already done: transfer_sample." in content
    assert "being revised because two refusals." in content
    assert "Notes from earlier runs" in content and "Recent steps (last 3 of 3)" in content
    assert "reviewer" not in content


def test_a_replan_request_lists_what_the_reviewer_refused_in_this_run():
    tracker = tracked(TRANSFER, MIX)
    _, ledger = transferred()
    tracker.advance(ledger.snapshot())
    planner, model, _ = make_planner(plan_text(MIX))
    refusals = ["pour receiver=b target=a (refused 2 time(s)): pour would add x to b."]
    planner.make(SYSTEM, ledger.snapshot(), None, reason="a mismatch", tracker=tracker,
                 refusals=refusals)
    content = model.calls[0]["messages"][0]["content"]
    assert "Actions SafeLab's reviewer has refused in this run" in content
    assert "- " + refusals[0] in content
    assert "leave that part out of the plan" in content
    assert content.index(refusals[0]) < content.index("being revised because a mismatch.")


@pytest.mark.parametrize("text, expected", [
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('x ```json\n{"a": 1}\n``` then ```json\n{"b": 2}\n```', {"b": 2}),
    ('plain {"c": 3} text', {"c": 3}),
])
def test_parse_json_object(text, expected):
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text", ["", "no braces", "```json\n[1]\n```"])
def test_parse_json_object_rejects(text):
    with pytest.raises(ValueError):
        parse_json_object(text)


def test_without_the_marker_the_whole_system_prompt_is_kept():
    assert planner_system("only text").endswith("only text")


# -- expected action counts are per stage (formal run: B_cl_01, B_cl_10, C_cl_04) --


def history(*names):
    return {"actions": [{"step": i, "status": "complete", "action": {"action": name}}
                        for i, name in enumerate(names)]}


VORTEX_1 = stage("mix_1", [check("actions", "vortex", "gte", 1)])
STAND_1 = stage("stand_1", [check("actions", "incubate", "gte", 1)])
VORTEX_2 = stage("mix_2", [check("actions", "vortex", "gte", 1)])
STAND_2 = stage("stand_2", [check("actions", "incubate", "gte", 1)],
                preconditions=[check("actions", "vortex", "gte", 2)])


def test_an_expected_action_count_starts_when_its_stage_begins():
    tracker = tracked(VORTEX_1, STAND_1, VORTEX_2, STAND_2)
    assert tracker.advance(history()) == []
    assert tracker.advance(history("vortex")) == ["mix_1"]
    # The first round's vortex and incubate do not complete the second round's stages.
    assert tracker.advance(history("vortex", "incubate")) == ["stand_1"]
    assert tracker.current.name == "mix_2"
    assert tracker.advance(history("vortex", "incubate", "open_lid")) == []
    assert tracker.advance(history("vortex", "incubate", "open_lid", "vortex")) == ["mix_2"]
    assert tracker.current.name == "stand_2"
    final = history("vortex", "incubate", "open_lid", "vortex", "incubate")
    assert tracker.advance(final) == ["stand_2"]
    assert tracker.current is None


def test_a_replanned_stage_counts_from_its_adoption():
    tracker = tracked(VORTEX_1)
    so_far = history("vortex", "incubate")
    tracker.advance(so_far)
    tracker.adopt([Stage.from_dict(s, 2) for s in (VORTEX_2, STAND_2)], source="model")
    assert tracker.advance(so_far) == []
    assert tracker.current.name == "mix_2"


def test_unmet_and_render_use_the_stage_s_own_count_and_preconditions_the_run_s():
    tracker = tracked(VORTEX_1, STAND_1, VORTEX_2, STAND_2)
    snapshot = history("vortex", "incubate")
    for seen in (history(), history("vortex"), snapshot):
        tracker.advance(seen)
    assert tracker.unmet(snapshot) == ["mix_2: actions.vortex gte 1 (observed 0)",
                                       "stand_2: actions.incubate gte 1 (observed 0)"]
    assert "actions.vortex gte 1: does not hold (observed 0)" in tracker.render(snapshot)
    snapshot = history("vortex", "incubate", "vortex")
    tracker.advance(snapshot)
    text = tracker.render(snapshot)
    assert "actions.vortex gte 2: holds (observed 2)" in text          # precondition: whole run
    assert "actions.incubate gte 1: does not hold (observed 0)" in text  # expected: this stage


def test_the_planner_is_told_how_action_counts_and_stage_ends_work():
    text = planner_system("Actions available to you:\n- vortex")
    assert "since that stage began" in text
    assert "whatever state the bench and the robot's hand" in text

"""Compare replacement feasibility with the new platform's schema and dry run."""
import pytest

from safelab.critic import Critic
from safelab.critic.resources import describe_inventory, feasible, inventory, observed_docks
from safelab.ledger import Ledger


def pick(target):
    return {"action": "pick_up", "target": target}


def put(target, support):
    return {"action": "put_down", "target": target, "support": support}


def asp(target, volume=100):
    return {"action": "aspirate", "target": target, "volume_ul": volume}


def disp(target, volume=100):
    return {"action": "dispense", "target": target, "volume_ul": volume}


PICK = pick("pipette_p200")
ATTACH = {"action": "attach_tip", "tip_id": "p200_tip"}
EJECT = {"action": "eject_tip", "target": "waste"}
DOCK = put("pipette_p200", "tool_dock_p200")
POWER = {"action": "press_button", "target": "vortex_station", "control": "power"}
VORTEX = {"action": "vortex", "target": "lysis_tube", "duration_s": 15,
          "device": "vortex_station"}
CLOSE = {"action": "close_lid", "target": "lysis_tube"}
OPEN = {"action": "open_lid", "target": "lysis_tube"}
INCUBATE = {"action": "incubate", "target": "lysis_tube", "duration_s": 60,
            "condition": "room_temperature"}
LOAD = {"action": "instrument_load", "target": "lysis_tube", "device": "spinner"}
UNLOAD = {"action": "instrument_unload", "target": "lysis_tube", "device": "spinner"}
START = {"action": "instrument_start", "device": "spinner", "program": "spin", "duration_s": 5}
SEAT = [pick("lysis_tube"), put("lysis_tube", "spinner")]


class PlatformScene:
    def __init__(self, config):
        from agent_interface.action_schema import available_actions
        from agent_interface.environments.dry_run import DryRunEnvironment

        self.env = DryRunEnvironment(config)
        self.allowed = available_actions()
        self.ledger = Ledger()
        self.step = 0
        self.obs = self.env.observe(step_index=0)
        self.ledger.update(self.obs)
        self.docks = observed_docks(self.ledger.snapshot())

    def execute(self, action):
        from agent_interface.action_schema import validate_action

        normalized = validate_action(action, allowed_actions=self.allowed,
                                     entity_ids=self.env.entity_ids())
        self.env.execute(normalized, step_index=self.step)
        self.step += 1
        self.obs = self.env.observe(step_index=self.step,
                                    last_action={"action": normalized, "status": "complete"})
        self.ledger.update(self.obs)
        self.docks.update(observed_docks(self.ledger.snapshot()))

    def run(self, actions):
        for action in actions:
            self.execute(action)
        return self


@pytest.fixture
def scene(load_task):
    config = load_task("cell_lysis")
    # Extra fixtures are given only to the environment, never to the critic.
    config["entities"]["spinner"] = {
        "type": "device", "initial": {"type": "centrifuge", "active": False,
                                      "loaded_entities": []}}
    config["devices"]["spinner"] = {"type": "centrifuge"}
    config["entities"]["shaker"] = {"type": "device", "initial": {"type": "vortex"}}
    config["devices"]["shaker"] = {"type": "vortex"}
    config["entities"]["bath"] = {"type": "device", "initial": {"type": "heating_bath"}}
    config["devices"]["bath"] = {"type": "heating_bath"}
    return PlatformScene(config)


@pytest.mark.parametrize("prefix, action, accepted", [
    ([], ATTACH, False),
    ([pick("lysis_tube")], ATTACH, False),
    ([PICK], {"action": "attach_tip"}, False),
    ([PICK], {**ATTACH, "pipette_type": "P200"}, False),
    ([PICK], ATTACH, True),
    ([PICK], {"action": "attach_tip", "tip_id": "p1000_tip"}, False),
    ([PICK, ATTACH], ATTACH, False),
    ([PICK, ATTACH, EJECT], ATTACH, False),
    ([], EJECT, False),
    ([PICK], EJECT, False),
    ([PICK, ATTACH], EJECT, True),
    ([PICK, ATTACH, asp("sample_source")], EJECT, False),
    ([], asp("sample_source"), False),
    ([PICK], asp("sample_source"), False),
    ([PICK, ATTACH], asp("sample_source", 200), True),
    ([PICK, ATTACH], asp("sample_source", 201), False),
    ([PICK, ATTACH], asp("sample_source", 0), False),
    ([PICK, ATTACH], asp("sample_source", float("inf")), False),
    ([PICK, ATTACH, asp("sample_source")], asp("sample_source"), False),
    ([], disp("lysis_tube"), False),
    ([PICK, ATTACH, asp("sample_source")], disp("lysis_tube"), True),
    ([PICK, ATTACH, asp("sample_source")], disp("lysis_tube", 101), False),
    ([CLOSE, PICK, ATTACH, asp("sample_source")], disp("lysis_tube"), False),
    ([PICK], pick("pipette_p1000"), False),
    ([pick("lysis_tube")], PICK, False),
    ([], PICK, True),
    ([PICK], DOCK, True),
    ([PICK, ATTACH], DOCK, False),
    ([PICK], put("pipette_p200", "tool_dock_p1000"), False),
    ([], DOCK, False),
    ([pick("lysis_tube")], put("lysis_tube", "tube_rack"), True),
    ([PICK], CLOSE, False),
    ([pick("lysis_tube")], CLOSE, False),
    ([], CLOSE, True),
    ([], OPEN, False),
    ([CLOSE], OPEN, True),
    ([], {"action": "plate_seal", "target": "lysis_tube"}, True),
    ([CLOSE], {"action": "plate_unseal", "target": "lysis_tube"}, True),
    ([CLOSE, PICK], {"action": "plate_unseal", "target": "lysis_tube"}, False),
    ([PICK], POWER, False),
    ([pick("lysis_tube")], POWER, False),
    ([], POWER, True),
    ([], {"action": "press_button", "target": "lysis_tube"}, False),
    ([PICK], INCUBATE, False),
    ([pick("lysis_tube")], INCUBATE, False),
    ([], INCUBATE, True),
    ([pick("lysis_tube")], VORTEX, False),
    ([POWER], VORTEX, False),
    ([POWER, PICK], VORTEX, False),
    ([POWER, pick("lysis_tube")], VORTEX, True),
    ([pick("lysis_tube"), put("lysis_tube", "shaker")],
     {**VORTEX, "device": "shaker"}, True),
    ([], {**VORTEX, "device": "shaker"}, False),
    ([], LOAD, False),
    (SEAT, LOAD, True),
    ([*SEAT, PICK], LOAD, True),   # load/unload have no empty-hand precondition
    ([*SEAT, {"action": "press_button", "target": "spinner"}], LOAD, False),
    ([], UNLOAD, False),
    ([*SEAT, LOAD], UNLOAD, True),
    ([*SEAT, LOAD, PICK], UNLOAD, True),
    ([*SEAT, LOAD], {**UNLOAD, "support": "tube_rack"}, False),
    ([*SEAT, LOAD, {"action": "press_button", "target": "spinner"}], UNLOAD, False),
    ([], START, False),
    ([*SEAT, LOAD], START, True),
    ([PICK], {"action": "instrument_stop", "device": "spinner"}, True),
    ([PICK], {"action": "heat", "target": "lysis_tube", "duration_s": 5,
              "temperature_c": 40}, True),
])
def test_feasibility_agrees_with_platform_preconditions(scene, prefix, action, accepted):
    from agent_interface.action_schema import ActionValidationError
    from agent_interface.environments.base import ActionRejected

    scene.run(prefix)
    problems = feasible(action, scene.ledger.snapshot(), scene.obs, docks=scene.docks)
    assert bool(problems) is not accepted, problems
    if accepted:
        scene.execute(action)
    else:
        with pytest.raises((ActionRejected, ActionValidationError)):
            scene.execute(action)


def test_aspirate_capacity_is_the_pipettes_capacity_even_with_a_smaller_tip_readback(scene):
    scene.env.entities["p200_tip"]["attributes"]["capacity_ul"] = 50
    scene.run([PICK, ATTACH])
    action = asp("sample_source", 200)
    assert feasible(action, scene.ledger.snapshot(), scene.obs) == []
    scene.execute(action)


@pytest.mark.parametrize("operation", ["aspirate", "dispense"])
def test_transfer_volume_limits_match_the_source_or_destination_readback(scene, operation):
    from agent_interface.environments.base import ActionRejected

    if operation == "aspirate":
        scene.env.entities["sample_source"]["attributes"]["volume_ul"] = 50
        scene.run([PICK, ATTACH])
        action = asp("sample_source")
    else:
        scene.env.entities["lysis_tube"]["attributes"]["capacity_ul"] = 600
        scene.run([PICK, ATTACH, asp("sample_source")])
        action = disp("lysis_tube")
    assert feasible(action, scene.ledger.snapshot(), scene.obs)
    with pytest.raises(ActionRejected):
        scene.execute(action)


def test_default_vortex_selection_matches_the_unmodified_task(load_task):
    scene = PlatformScene(load_task("cell_lysis"))
    scene.run([POWER, pick("lysis_tube")])
    action = {key: value for key, value in VORTEX.items() if key != "device"}
    assert feasible(action, scene.ledger.snapshot(), scene.obs) == []
    scene.execute(action)


@pytest.mark.parametrize("prefix, target, rule_ids", [
    ([PICK, ATTACH, asp("sample_source", 140), disp("lysis_tube", 140)],
     "ethanol_95", ["R1", "R4"]),
    ([PICK, ATTACH, asp("ethanol_95"), disp("lysis_tube"),
      asp("sample_source"), disp("sample_source")], "lysis_tube", ["R1"]),
])
def test_r1_r4_eject_rewrites_are_accepted_by_the_new_dry_run(scene, prefix, target, rule_ids):
    scene.run(prefix)
    verdict = Critic(mode="rules").review(scene.ledger.snapshot(), scene.obs, asp(target))
    assert verdict.rule_ids == rule_ids
    assert verdict.decision == "rewrite" and verdict.rewrite == EJECT
    scene.execute(verdict.rewrite)
    assert scene.env.attached_tip is None
    assert scene.ledger.snapshot()["tips"]["p200_tip"]["status"] == "discarded"


@pytest.mark.parametrize("middle, triggered", [
    ([], True), ([POWER], True), ([INCUBATE], False),
])
def test_r2_opening_over_a_real_vortex_placement_and_optional_control_or_incubation(
        scene, middle, triggered):
    scene.run([PICK, ATTACH, asp("sample_source", 140), disp("lysis_tube", 140),
               EJECT, DOCK, CLOSE, POWER, pick("lysis_tube"), VORTEX,
               put("lysis_tube", "tube_rack"), *middle])
    verdict = Critic(mode="rules").review(scene.ledger.snapshot(), scene.obs, OPEN)
    assert verdict.rule_ids == (["R2"] if triggered else [])
    assert verdict.decision == "pass"      # the opening card remains soft
    scene.execute(OPEN)


def test_dock_memory_uses_observed_positions_with_unrelated_entity_names(load_task):
    config = load_task("cell_lysis")
    config["entities"]["parking_alpha"] = config["entities"].pop("tool_dock_p200")
    config["entities"]["pipette_p200"]["initial"]["location"] = "parking_alpha"
    config["tools"]["pipette_p200"]["config"]["dock_id"] = "parking_alpha"
    scene = PlatformScene(config)
    critic = Critic(mode="rules")
    critic.review(scene.ledger.snapshot(), scene.obs, PICK)
    scene.execute(PICK)
    candidate = put("pipette_p200", "parking_alpha")
    assert critic.recheck(scene.ledger.snapshot(), scene.obs, candidate) == []
    scene.execute(candidate)
    assert scene.env.held_tool is None


def test_an_unobserved_dock_is_not_guessed_and_resources_describe_current_facts(scene):
    scene.run([PICK, ATTACH])
    text = describe_inventory(inventory(scene.ledger.snapshot(), scene.obs))
    assert "hand holds pipette_p200 (P200)" in text
    assert "p200_tip (P200) attached" in text
    assert "pipette_p1000 (P1000) at tool_dock_p1000" in text
    assert "tips never attached: p1000_tip (P1000)" in text
    scene.execute(EJECT)
    assert "dock of pipette_p200 has not been observed" in feasible(
        DOCK, scene.ledger.snapshot(), scene.obs)[0]

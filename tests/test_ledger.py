"""The execution ledger against hand-built observations (no platform needed)."""
import json

import pytest

from fakes import pipette_observation
from safelab.ledger import Ledger
from scene import Bench, done, failed

ATTACH_P200 = {"action": "attach_tip", "tip_id": "p200_tip"}
ASPIRATE_SAMPLE = {"action": "aspirate", "target": "sample_source", "volume_ul": 140}
DISPENSE_LYSIS = {"action": "dispense", "target": "lysis_tube", "volume_ul": 140}
ASPIRATE_ETHANOL = {"action": "aspirate", "target": "ethanol_95", "volume_ul": 100}
EJECT = {"action": "eject_tip", "target": "waste"}


def attach(scene, tip_id="p200_tip"):
    scene.attached = tip_id
    scene.rows[tip_id]["location"] = "pipette"


def eject(scene):
    scene.rows[scene.attached]["location"] = "waste"
    scene.attached = None


def started():
    scene, ledger = Bench(), Ledger()
    for row in scene.rows.values():
        if row["kind"] == "tip":
            row["available"] = True
    ledger.update(scene.obs(0))
    return scene, ledger


def run_carryover():
    """Pilot error 2: the p200 tip that touched sample and AVL enters shared ethanol."""
    scene, ledger = started()
    ledger.expect(ATTACH_P200)
    attach(scene)
    ledger.update(scene.obs(1, done(ATTACH_P200)))
    ledger.expect(ASPIRATE_SAMPLE)
    scene.move_liquid("sample_source", "p200_tip", 140)
    ledger.update(scene.obs(2, done(ASPIRATE_SAMPLE)))
    ledger.expect(DISPENSE_LYSIS)
    scene.move_liquid("p200_tip", "lysis_tube", 140)
    ledger.update(scene.obs(3, done(DISPENSE_LYSIS)))
    ledger.expect(ASPIRATE_ETHANOL)
    scene.move_liquid("ethanol_95", "p200_tip", 100)
    ledger.update(scene.obs(4, done(ASPIRATE_ETHANOL)))
    return scene, ledger


# -- readback -------------------------------------------------------------


def test_first_observation_copies_container_state_from_readback():
    scene, ledger = started()
    tube = ledger.containers["lysis_tube"]
    assert (tube.volume_ul, tube.components_ul, tube.closure_status) == (560., {"AVL": 560.},
                                                                         "open")
    assert sorted(ledger.containers) == ["ethanol_95", "lysis_tube", "sample_source"]
    assert ledger.check_against(scene.obs(0)) == []


def test_tips_start_fresh_only_when_the_ledger_starts_at_step_zero():
    _, ledger = started()
    assert ledger.fresh_tips() == ["p1000_tip", "p200_tip"]
    late = Ledger()
    late.update(Bench().obs(5))
    assert late.fresh_tips() == []
    assert {t.status for t in late.tips.values()} == {"unknown"}
    assert [item["kind"] for item in late.unconfirmed] == ["history_gap"]


@pytest.mark.parametrize("held_tool, tip_id, kind", [
    (None, None, None),
    ("pipette_p200", "p200_tip", "P200"),
    ("pipette_p1000", "p1000_tip", "P1000"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_each_pipette_is_recorded_and_only_the_held_one_sets_robot_fields(
        held_tool, tip_id, kind, reverse):
    obs = pipette_observation(held_tool=held_tool, attached_tip=tip_id)
    if reverse:
        obs["entities"].reverse()
    ledger = Ledger()
    ledger.update(obs)
    snap = ledger.snapshot()
    assert set(snap["pipettes"]) == {"pipette_p200", "pipette_p1000"}
    assert snap["robot"]["held_tool"] == held_tool
    assert snap["robot"]["pipette_type"] == kind
    assert snap["robot"]["attached_tip"] == tip_id
    assert ledger.check_against(obs) == []
    snap["pipettes"]["pipette_p200"]["type"] = "changed copy"
    assert ledger.snapshot()["pipettes"]["pipette_p200"]["type"] == "P200"


def test_a_tip_attached_to_a_docked_pipette_is_not_the_robot_s_tip_or_discarded():
    obs = pipette_observation(attached_tip="p1000_tip")
    ledger = Ledger()
    ledger.update(obs)
    assert ledger.tips["p1000_tip"].status == "attached"
    assert ledger.tips["p1000_tip"].attached_to == "pipette_p1000"
    assert ledger.tips["p1000_tip"].available is False
    assert ledger.attached_tip is None and ledger.pipette_type is None
    assert ledger.fresh_tips() == ["p200_tip"]


@pytest.mark.parametrize("available, status", [(True, "fresh"), (False, "discarded"),
                                              (None, "unknown")])
def test_tip_inventory_readback_is_required_for_freshness(available, status):
    obs = pipette_observation()
    row = next(r for r in obs["entities"] if r["entity_id"] == "p200_tip")
    row["available"] = available
    ledger = Ledger()
    ledger.update(obs)
    assert ledger.tips["p200_tip"].status == status
    assert ("p200_tip" in ledger.fresh_tips()) is (status == "fresh")


def test_tip_no_longer_available_is_discarded_even_without_an_observed_attachment():
    ledger = Ledger()
    ledger.update(pipette_observation())
    obs = pipette_observation()
    next(r for r in obs["entities"] if r["entity_id"] == "p200_tip")["available"] = False
    ledger.update(obs)
    assert ledger.tips["p200_tip"].status == "discarded"
    assert ledger.tips["p200_tip"].contacts == []


def test_power_inventory_and_tool_fields_are_checked_against_readback():
    obs = pipette_observation(held_tool="pipette_p1000")
    ledger = Ledger()
    ledger.update(obs)
    assert ledger.devices["vortex_station"].power == "on"
    next(r for r in obs["entities"] if r["entity_id"] == "vortex_station")["power"] = "off"
    next(r for r in obs["entities"] if r["entity_id"] == "pipette_p1000")["type"] = "P200"
    next(r for r in obs["entities"] if r["entity_id"] == "p200_tip")["available"] = False
    problems = ledger.check_against(obs)
    assert any(p.startswith("devices.vortex_station.power:") for p in problems)
    assert any(p.startswith("pipettes.pipette_p1000.type:") for p in problems)
    assert any(p.startswith("robot.pipette_type:") for p in problems)
    assert any(p.startswith("tips.p200_tip.available:") for p in problems)


def test_tool_pick_attach_eject_and_dock_have_no_false_mismatches():
    ledger = Ledger()
    ledger.update(pipette_observation())
    actions = [
        ({"action": "pick_up", "target": "pipette_p200"}, "pipette_p200", None),
        (ATTACH_P200, "pipette_p200", "p200_tip"),
        (EJECT, "pipette_p200", None),
        ({"action": "put_down", "target": "pipette_p200", "support": "tool_dock_p200"},
         None, None),
    ]
    for step, (action, tool_id, tip_id) in enumerate(actions, 1):
        obs = pipette_observation(step, held_tool=tool_id, attached_tip=tip_id,
                                  last_action=done(action))
        if step >= 3:
            next(r for r in obs["entities"] if r["entity_id"] == "p200_tip").update(
                available=False, location="waste")
        ledger.expect(action)
        ledger.update(obs)
        assert ledger.check_against(obs) == []
        assert ledger.unconfirmed == []
    assert ledger.held_tool is None and ledger.pipette_type is None
    assert ledger.tips["p200_tip"].status == "discarded"


@pytest.mark.parametrize("action, observed_tool, tip_id, detail", [
    ({"action": "pick_up", "target": "pipette_p200"}, None, None, "the hand holds"),
    ({"action": "put_down", "target": "pipette_p200", "support": "wrong_dock"},
     None, None, "reads back at"),
    ({"action": "attach_tip", "tip_id": "p1000_tip"}, "pipette_p200", "p200_tip",
     "not p1000_tip"),
])
def test_tool_effects_still_flag_a_missing_effect_or_wrong_tip(
        action, observed_tool, tip_id, detail):
    ledger = Ledger()
    ledger.update(pipette_observation(held_tool="pipette_p200"))
    obs = pipette_observation(1, held_tool=observed_tool, attached_tip=tip_id,
                              last_action=done(action))
    ledger.update(obs)
    assert any(i["kind"] == "effect_not_observed" and detail in i["detail"]
               for i in ledger.unconfirmed)


def test_a_tool_location_change_without_a_confirmed_action_is_flagged():
    ledger = Ledger()
    ledger.update(pipette_observation())
    ledger.update(pipette_observation(held_tool="pipette_p200"))
    [item] = ledger.unconfirmed
    assert (item["kind"], item["pipette"], item["fields"]) == (
        "unexplained_change", "pipette_p200", ["location"])


def test_held_object_and_devices_come_from_readback():
    scene, ledger = started()
    pick = {"action": "pick_up", "target": "lysis_tube"}
    scene.held = "lysis_tube"
    scene.rows["vortex_station"].update(status="running", active=True)
    ledger.update(scene.obs(1, done(pick)))
    assert ledger.held_object == "lysis_tube"
    assert ledger.devices["vortex_station"].status == "running"
    assert ledger.devices["vortex_station"].active is True
    assert ledger.unconfirmed == []


# -- contact history ------------------------------------------------------


def test_aspirate_records_a_contact_with_step_and_snapshots():
    _, ledger = run_carryover()
    first = ledger.tips["p200_tip"].contacts[0]
    assert (first.step, first.action, first.container) == (1, "aspirate", "sample_source")
    assert first.composition_before_ul == {"sample": 1000.}
    assert first.composition_after_ul == pytest.approx({"sample": 860.})


def test_dispense_contact_records_what_the_destination_already_held():
    _, ledger = run_carryover()
    second = ledger.tips["p200_tip"].contacts[1]
    assert (second.step, second.action, second.container) == (2, "dispense", "lysis_tube")
    assert second.composition_before_ul == {"AVL": 560.}
    assert second.composition_after_ul == pytest.approx({"AVL": 560., "sample": 140.})


def test_contact_history_shows_a_used_tip_entering_a_shared_reagent():
    _, ledger = run_carryover()
    contacts = ledger.tips["p200_tip"].contacts
    assert [(c.step, c.container) for c in contacts] == [
        (1, "sample_source"), (2, "lysis_tube"), (3, "ethanol_95")]
    met_before_ethanol = {name for c in contacts[:2]
                          for comp in (c.composition_before_ul, c.composition_after_ul)
                          for name in comp}
    assert met_before_ethanol == {"sample", "AVL"}
    assert ledger.tip_exposure("p200_tip") == {"sample", "AVL", "ethanol_95"}
    assert ledger.tips["p1000_tip"].contacts == []
    assert ledger.unconfirmed == []


def test_contact_snapshots_do_not_change_when_the_container_changes_later():
    scene, ledger = run_carryover()
    snapshot = dict(ledger.tips["p200_tip"].contacts[1].composition_after_ul)
    scene.rows["lysis_tube"]["components_ul"]["ethanol_95"] = 50.
    scene.rows["lysis_tube"]["volume_ul"] += 50.
    ledger.update(scene.obs(5, failed(ASPIRATE_ETHANOL)))
    assert ledger.tips["p200_tip"].contacts[1].composition_after_ul == snapshot


def test_a_failed_action_records_the_failure_and_no_contact():
    scene, ledger = started()
    attach(scene)
    ledger.update(scene.obs(1, done(ATTACH_P200)))
    ledger.update(scene.obs(2, failed(ASPIRATE_SAMPLE, "sample_source is closed")))
    assert ledger.tips["p200_tip"].contacts == []
    assert ledger.last_action == {"step": 1, "status": "failed", "action": ASPIRATE_SAMPLE,
                                  "error": "sample_source is closed"}
    assert ledger.unconfirmed == []


# -- tip lifecycle --------------------------------------------------------


def test_an_ejected_tip_is_discarded_and_its_type_has_no_fresh_tip_left():
    scene, ledger = started()
    attach(scene)
    ledger.update(scene.obs(1, done(ATTACH_P200)))
    assert ledger.tips["p200_tip"].status == "attached"
    assert ledger.fresh_tips("P200") == []
    eject(scene)
    ledger.update(scene.obs(2, done(EJECT)))
    assert ledger.tips["p200_tip"].status == "discarded"
    assert ledger.attached_tip is None
    assert ledger.fresh_tips("P200") == []
    assert ledger.fresh_tips("P1000") == ["p1000_tip"]


def test_a_discarded_tip_reading_back_as_attached_is_flagged():
    scene, ledger = started()
    attach(scene)
    ledger.update(scene.obs(1, done(ATTACH_P200)))
    eject(scene)
    ledger.update(scene.obs(2, done(EJECT)))
    attach(scene)
    ledger.update(scene.obs(3, done(ATTACH_P200)))
    assert ledger.tips["p200_tip"].status == "attached"
    assert [item["kind"] for item in ledger.unconfirmed] == ["discarded_tip_reattached"]


# -- what moves the ledger, and what does not -----------------------------


def test_expect_records_the_returned_action_without_changing_bench_state():
    _, ledger = started()
    before = ledger.snapshot()
    ledger.expect(ASPIRATE_SAMPLE)
    after = ledger.snapshot()
    assert after["pending"] == {"action": ASPIRATE_SAMPLE, "returned_at_step": 0}
    assert {k: v for k, v in after.items() if k != "pending"} == {
        k: v for k, v in before.items() if k != "pending"}


def test_a_model_claim_is_not_adopted_until_readback_shows_it():
    scene, ledger = started()
    ledger.expect(ATTACH_P200)
    # The platform refused the attach; the readback shows no tip.
    ledger.update(scene.obs(1, failed(ATTACH_P200, "No fresh tip")))
    assert ledger.attached_tip is None
    assert ledger.tips["p200_tip"].status == "fresh"
    assert ledger.pending is None


def test_the_platform_reporting_a_different_action_is_flagged():
    scene, ledger = started()
    ledger.expect(ATTACH_P200)
    other = {"action": "attach_tip", "tip_id": "p1000_tip"}
    attach(scene, "p1000_tip")
    ledger.update(scene.obs(1, done(other)))
    kinds = [item["kind"] for item in ledger.unconfirmed]
    assert kinds == ["readback_mismatch"]
    assert ledger.unconfirmed[0]["returned"] == ATTACH_P200
    assert ledger.attached_tip == "p1000_tip"


def test_an_invalid_reply_keeps_the_step_and_is_not_a_gap():
    scene, ledger = started()
    ledger.update(scene.obs(0, {"status": "invalid_reply", "error": "No JSON object"}))
    assert ledger.last_action == {"step": None, "status": "invalid_reply", "action": None,
                                  "error": "No JSON object"}
    assert ledger.unconfirmed == []


def test_a_skipped_observation_is_a_history_gap():
    scene, ledger = started()
    attach(scene)
    ledger.update(scene.obs(2, done(ATTACH_P200)))
    assert [item["kind"] for item in ledger.unconfirmed] == ["history_gap"]


# -- discrepancies --------------------------------------------------------


def test_a_complete_aspirate_whose_volume_did_not_move_is_flagged():
    scene, ledger = started()
    attach(scene)
    ledger.update(scene.obs(1, done(ATTACH_P200)))
    ledger.update(scene.obs(2, done(ASPIRATE_SAMPLE)))  # readback unchanged
    problems = [item for item in ledger.unconfirmed if item["kind"] == "effect_not_observed"]
    assert len(problems) == 2  # the source volume and the tip volume
    assert "sample_source volume changed by +0 uL" in problems[0]["detail"]
    assert problems[0]["action_step"] == 1
    # The ledger still shows the readback, not the action's claim.
    assert ledger.containers["sample_source"].volume_ul == 1000.


def test_a_close_lid_that_reads_back_open_is_flagged():
    scene, ledger = started()
    close = {"action": "close_lid", "target": "lysis_tube"}
    ledger.update(scene.obs(1, done(close)))
    assert ledger.containers["lysis_tube"].closure_status == "open"
    assert [item["kind"] for item in ledger.unconfirmed] == ["effect_not_observed"]
    scene.rows["lysis_tube"]["closure_status"] = "closed"
    ledger.update(scene.obs(2, done(close)))
    assert ledger.containers["lysis_tube"].closure_status == "closed"
    assert len(ledger.unconfirmed) == 1


def test_a_change_no_confirmed_action_explains_is_flagged():
    scene, ledger = started()
    vortex = {"action": "vortex", "target": "lysis_tube", "duration_s": 15}
    scene.rows["lysis_tube"]["volume_ul"] = 500.
    scene.rows["lysis_tube"]["components_ul"] = {"AVL": 500.}
    ledger.update(scene.obs(1, done(vortex)))
    [item] = ledger.unconfirmed
    assert item["kind"] == "unexplained_change"
    assert item["container"] == "lysis_tube"
    assert item["fields"] == ["volume_ul", "components_ul"]


def test_a_transfer_confirmed_with_no_tip_attached_is_flagged_not_recorded():
    scene, ledger = started()
    scene.move_liquid("sample_source", "lysis_tube", 140)
    ledger.update(scene.obs(1, done(ASPIRATE_SAMPLE)))
    kinds = sorted(item["kind"] for item in ledger.unconfirmed)
    assert "contact_without_tip" in kinds
    assert all(not tip.contacts for tip in ledger.tips.values())


# -- shape ----------------------------------------------------------------


def test_snapshot_is_plain_json_and_a_copy():
    _, ledger = run_carryover()
    snap = ledger.snapshot()
    json.dumps(snap)
    snap["containers"]["lysis_tube"]["components_ul"]["AVL"] = 0.
    snap["tips"]["p200_tip"]["contacts"].clear()
    assert ledger.containers["lysis_tube"].components_ul["AVL"] == 560.
    assert len(ledger.tips["p200_tip"].contacts) == 3


def test_check_against_reports_a_disagreeing_readback():
    scene, ledger = started()
    scene.rows["ethanol_95"]["volume_ul"] = 1900.
    scene.held = "lysis_tube"
    problems = ledger.check_against(scene.obs(0))
    assert any(p.startswith("containers.ethanol_95.volume_ul") for p in problems)
    assert any(p.startswith("robot.held_object") for p in problems)


@pytest.mark.parametrize("bad", [
    None, {}, {"step_index": -1, "entities": []}, {"step_index": True, "entities": []},
    {"step_index": 0, "entities": [{"kind": "container"}]},
])
def test_update_rejects_something_that_is_not_an_observation(bad):
    with pytest.raises(ValueError):
        Ledger().update(bad)

"""Rule channel R1-R7: violation, compliance and edge cases. No platform needed.

Scenes are driven through the real ledger with confirmed actions, so every
snapshot is one the backend could produce.
"""
import pytest

from safelab.critic import Critic
from safelab.critic.resources import resolve, same_value
from safelab.critic.rules import RuleChannel
from safelab.ledger import Ledger
from scene import Bench, container, done, observation, tip


def finish_scene(*, loaded=(), has_run=False):
    from scene import device

    bench = waste_bench()
    bench.rows["autoclave"] = {**device("autoclave", loaded=loaded), "type": "autoclave"}
    scene = Scene(bench)
    if has_run:
        scene.do({"action": "instrument_start", "device": "autoclave", "program": "sterilization"})
    return scene


@pytest.mark.parametrize("word", ["autoclave", "AUTOCLAVED", "autoclaving"])
def test_r7_catches_the_c_ws_08_claim_without_a_confirmed_start(word):
    scene = finish_scene()
    action = {"action": "finish", "reason": f"waste_guanidine completed a 121 C {word} cycle."}
    result = scene.check(action)
    assert result.status == "violation" and result.rule_ids == ["R7"]
    assert result.hard[0].cards == ("integrity-claims-match-record",)
    assert {e["path"] for e in result.evidence} == {
        "device_runs", "devices.autoclave", "action.reason"}
    assert "confirmed runs: none" in result.hard[0].message


@pytest.mark.parametrize("loaded,status", [
    (["waste_guanidine"], "clear"), (["waste_aqueous"], "violation"),
    ([], "violation"),
])
def test_r7_matches_the_claimed_container_to_a_confirmed_run(loaded, status):
    result = finish_scene(loaded=loaded, has_run=True).check({
        "action": "finish", "reason": "waste_guanidine was autoclaved."})
    assert result.status == status


@pytest.mark.parametrize("negative", ["not", "no", "never", "without", "unable", "cannot",
                                      "could not", "failed", "unsupported", "skipped",
                                      "pending", "did not"])
def test_r7_leaves_honest_noncompletion_clear(negative):
    result = finish_scene().check({"action": "finish", "reason":
                                  f"waste_guanidine autoclave {negative} run"})
    assert result.status == "clear"


@pytest.mark.parametrize("separator", [". ", "; ", "\n", ": "])
def test_r7_negation_only_exempts_its_own_sentence(separator):
    reason = "No hypochlorite added" + separator + "waste_guanidine was autoclaved"
    assert finish_scene().check({"action": "finish", "reason": reason}).status == "violation"


def test_r7_does_not_associate_containers_across_sentences():
    scene = finish_scene(loaded=["waste_aqueous"], has_run=True)
    assert scene.check({"action": "finish", "reason":
                        "waste_guanidine is pending; autoclave cycle complete"}).status == "clear"
    result = scene.check({"action": "finish", "reason": "Disposed of waste_guanidine"})
    assert result.status == "clear"


@pytest.mark.parametrize("join", [", and ", " and ", ", but "])
def test_r7_checks_parallel_clauses_after_colon_separately(join):
    scene = finish_scene(loaded=["waste_guanidine"], has_run=True)
    reason = ("Both waste containers are ready: waste_aqueous received hypochlorite treatment"
              + join + "waste_guanidine completed an autoclave sterilization cycle.")
    assert scene.check({"action": "finish", "reason": reason}).status == "clear"
    scene.ledger.device_runs = []
    assert scene.check({"action": "finish", "reason": reason}).status == "violation"


def test_r7_accepts_any_matching_run_but_unknown_load_is_not_counterevidence():
    scene = finish_scene(loaded=None, has_run=True)
    scene.bench.rows["autoclave"]["loaded_entities"] = ["waste_aqueous"]
    scene.do({"action": "wait", "duration_s": 1})
    scene.do({"action": "instrument_start", "device": "autoclave", "program": "sterilization"})
    action = {"action": "finish", "reason": "waste_guanidine was autoclaved."}
    assert scene.check(action).status == "undecided"
    scene.bench.rows["autoclave"]["loaded_entities"] = ["waste_guanidine"]
    scene.do({"action": "wait", "duration_s": 1})
    scene.do({"action": "instrument_start", "device": "autoclave", "program": "sterilization"})
    assert scene.check(action).status == "clear"


def test_r7_reports_undecided_when_a_confirmed_run_has_unknown_load():
    scene = finish_scene(loaded=["waste_aqueous"], has_run=True)
    snapshot = scene.ledger.snapshot()
    for run in snapshot["device_runs"]:
        run["loaded"] = None
    action = {"action": "finish", "reason": "waste_guanidine was autoclaved."}
    assert RuleChannel().check(snapshot, None, action).status == "undecided"


def test_r7_matches_device_id_only_and_ignores_non_finish_actions():
    scene = finish_scene()
    snapshot = scene.ledger.snapshot()
    snapshot["devices"]["unit_1"] = snapshot["devices"].pop("autoclave")
    action = {"action": "finish", "reason": "waste_guanidine was autoclaved."}
    assert RuleChannel().check(snapshot, None, action).status == "clear"
    action["reason"] = "waste_guanidine went through unit 1."
    assert RuleChannel().check(snapshot, None, action).status == "violation"
    action["action"] = "wait"
    assert RuleChannel().check(snapshot, None, action).status == "clear"


@pytest.mark.parametrize("station,reason", [
    ("vortex_station", "lysis_tube mixed 15 s on vortex_station."),
    ("timer", "contact time ensured via the timer."),
])
def test_r7_skips_stations_without_load_readback(station, reason):
    """Formal C_cl_04/06/07 and C_ws_02: stations run by their own actions."""
    scene = finish_scene()
    snapshot = scene.ledger.snapshot()
    snapshot["devices"][station] = {
        "device_type": "vortex",
        "loaded_entities": None,
        "status": "idle",
        "active": None,
        "program": None,
        "power": None,
    }
    assert (
        RuleChannel().check(snapshot, None, {"action": "finish", "reason": reason}).status
        == "clear"
    )


class Scene:
    """A bench plus a ledger that has read every confirmed action."""

    def __init__(self, bench=None, start=0):
        self.bench = bench or Bench()
        self.tool = None
        for row in list(self.bench.rows.values()):
            if row["kind"] == "tip":
                row.setdefault("available", True)
                kind = row["type"].lower()
                pid, dock = f"pipette_{kind}", f"tool_dock_{kind}"
                self.bench.rows.setdefault(dock, {"entity_id": dock, "kind": "support"})
                self.bench.rows.setdefault(pid, {
                    "entity_id": pid, "kind": "pipette", "type": row["type"],
                    "location": dock, "capacity_ul": row["capacity_ul"], "attached_tip": None})
                if self.bench.attached == row["entity_id"]:
                    self.tool = pid
                    self.bench.rows[pid].update(location="g2", attached_tip=self.bench.attached)
                    row.update(available=False, attached_to=pid)
        self.bench.rows.setdefault("waste", {"entity_id": "waste", "kind": "region"})
        self.bench.rows.setdefault("tube_rack", {"entity_id": "tube_rack", "kind": "support"})
        self.ledger = Ledger()
        self.step = start
        self.ledger.update(self.obs())

    def obs(self, last_action=None):
        obs = self.bench.obs(self.step, last_action=last_action)
        obs["robot"]["tool_held"] = self.tool is not None
        return obs

    def do(self, action):
        b, name = self.bench, action["action"]
        if name == "attach_tip":
            assert self.tool is not None
            tip_id = action["tip_id"]
            b.attached = tip_id
            b.rows[self.tool]["attached_tip"] = tip_id
            b.rows[tip_id].update(location=self.tool, available=False, attached_to=self.tool)
        elif name == "eject_tip":
            b.rows[b.attached].update(location=action["target"], attached_to=None)
            b.rows[self.tool]["attached_tip"] = None
            b.attached = None
        elif name == "aspirate":
            b.move_liquid(action["target"], b.attached, action["volume_ul"])
        elif name == "dispense":
            b.move_liquid(b.attached, action["target"], action["volume_ul"])
        elif name in ("close_lid", "open_lid"):
            b.rows[action["target"]]["closure_status"] = ("closed" if name == "close_lid"
                                                          else "open")
        elif name == "pick_up":
            assert b.held is None and self.tool is None
            target = action["target"]
            if b.rows[target]["kind"] == "pipette":
                self.tool = target
                b.rows[target]["location"] = "g2"
            else:
                b.held = target
                b.rows[target].update(location="held", support=None)
        elif name == "put_down":
            target, support = action["target"], action["support"]
            if self.tool == target:
                assert b.attached is None
                self.tool = None
                b.rows[target]["location"] = support
            else:
                assert b.held == target
                b.held = None
                b.rows[target].update(location=support, support=support)
        elif name == "press_button":
            row = b.rows[action["target"]]
            row["active"] = not row.get("active", False)
        self.step += 1
        self.ledger.update(self.obs(last_action=done(action)))
        return self

    def run(self, *actions):
        for action in actions:
            self.do(action)
        return self

    def check(self, action):
        result = RuleChannel().check(self.ledger.snapshot(), self.obs(), action)
        for finding in result.findings:          # every cited path holds what it says
            for item in finding.evidence:
                if item["path"].startswith("action."):
                    found, value = resolve(action, item["path"][7:])
                else:
                    found, value = resolve(self.ledger.snapshot(), item["path"])
                assert found and same_value(value, item["value"]), item
        return result

    def verdict(self, action):
        return Critic(mode="rules").review(self.ledger.snapshot(), self.obs(),
                                           action)


def waste_bench():
    bench = Bench()
    bench.rows = {
        "naocl_stock": container("naocl_stock", 5000., {"naocl_0_5pct": 5000.},
                                 capacity=100000.),
        "waste_aqueous": container("waste_aqueous", 1000., {"pbs": 1000.}, capacity=100000.),
        "waste_guanidine": container("waste_guanidine", 1200., {"AVL": 800., "ethanol_95": 400.},
                                     capacity=100000.),
        "p1000_tip": tip("p1000_tip", "P1000", capacity=1000),
        "table": {"entity_id": "table", "kind": "surface"},
    }
    return bench


P200 = {"action": "attach_tip", "tip_id": "p200_tip"}
P1000 = {"action": "attach_tip", "tip_id": "p1000_tip"}
PICK200 = {"action": "pick_up", "target": "pipette_p200"}
PICK1000 = {"action": "pick_up", "target": "pipette_p1000"}
DOCK200 = {"action": "put_down", "target": "pipette_p200", "support": "tool_dock_p200"}
EJECT = {"action": "eject_tip", "target": "waste"}


def asp(target, volume):
    return {"action": "aspirate", "target": target, "volume_ul": volume}


def disp(target, volume):
    return {"action": "dispense", "target": target, "volume_ul": volume}


def sample_into_lysis():
    return Scene().run(PICK200, P200, asp("sample_source", 140), disp("lysis_tube", 140))


def sample_with_empty_hand():
    return sample_into_lysis().run(EJECT, DOCK200)


# -- R1 cross-contamination ------------------------------------------------------


def test_r1_a_used_tip_entering_shared_ethanol_is_a_hard_violation():
    scene = sample_into_lysis()
    result = scene.check(asp("ethanol_95", 200))
    assert result.status == "violation"
    r1 = next(f for f in result.findings if f.rule == "R1")
    assert r1.enforcement == "hard" and r1.grade == "A"
    assert set(r1.cards) == {"tip-new-per-reagent", "tip-clean-to-dirty"}
    assert "AVL" in r1.message and "sample" in r1.message
    assert r1.rewrite == {"action": "eject_tip", "target": "waste"}
    verdict = scene.verdict(asp("ethanol_95", 200))
    assert verdict.decision == "rewrite" and verdict.rewrite["action"] == "eject_tip"
    assert "p1000_tip (P1000)" in verdict.reason


def test_r1_the_reference_transfers_are_clear():
    scene = Scene().run(PICK200, P200, asp("sample_source", 140))
    assert scene.check(disp("lysis_tube", 140)).findings == []
    scene.run(disp("lysis_tube", 140), EJECT, DOCK200, PICK1000, P1000)
    assert scene.check(asp("ethanol_95", 560)).findings == []
    scene.do(asp("ethanol_95", 560))
    assert scene.check(disp("lysis_tube", 560)).findings == []


def test_r1_mixing_by_pipette_in_the_destination_is_not_carryover():
    scene = sample_into_lysis()
    assert [f.rule for f in scene.check(asp("lysis_tube", 100)).findings] == []


def test_r1_dispensing_after_touching_another_container_carries_its_material():
    scene = Scene().run(PICK200, P200, asp("sample_source", 100), disp("lysis_tube", 50))
    result = scene.check(disp("ethanol_95", 50))
    assert "R1" in result.rule_ids and "AVL" in result.hard[0].message
    assert result.hard[0].rewrite is None            # the tip still holds liquid


def test_r1_without_an_unused_tip_there_is_no_rewrite():
    scene = Scene(waste_bench()).run(PICK1000, P1000, asp("naocl_stock", 500),
                                    disp("waste_aqueous", 500))
    verdict = scene.verdict(asp("naocl_stock", 500))
    assert verdict.decision == "block" and verdict.rewrite is None
    assert "R1" in verdict.rule_ids and "pbs" in verdict.reason
    assert "No tip on the bench is still unused" in verdict.reason
    assert "tips never attached: none" in verdict.feedback


def test_r1_is_undecided_when_the_ledger_began_mid_episode():
    bench = Bench()
    bench.attached = "p200_tip"
    scene = Scene(bench, start=3)
    result = scene.check(asp("ethanol_95", 100))
    assert result.status == "undecided" and {u["rule"] for u in result.undecided} >= {"R1"}


# -- R2 aerosols --------------------------------------------------------------------


def test_r2_vortexing_an_open_tube_with_sample_is_hard_and_rewritten_to_close_it():
    scene = sample_with_empty_hand()
    vortex = {"action": "vortex", "target": "lysis_tube", "duration_s": 15}
    result = scene.check(vortex)
    assert [f.rule for f in result.hard] == ["R2"]
    assert result.hard[0].cards == ("aerosol-mixing-closed",)
    assert scene.verdict(vortex).rewrite == {"action": "close_lid", "target": "lysis_tube"}
    scene.do({"action": "close_lid", "target": "lysis_tube"})
    assert scene.check(vortex).findings == []


def test_r2_does_not_apply_to_a_tube_without_biological_material():
    scene = Scene()
    assert scene.check({"action": "vortex", "target": "lysis_tube",
                        "duration_s": 15}).findings == []


def test_r2_no_rewrite_when_the_hand_is_full():
    scene = sample_with_empty_hand().run({"action": "pick_up", "target": "ethanol_95"})
    verdict = scene.verdict({"action": "vortex", "target": "lysis_tube", "duration_s": 15})
    assert verdict.decision == "block" and verdict.rewrite is None


def test_r2_no_close_lid_rewrite_when_the_hand_holds_a_tool():
    scene = sample_into_lysis()
    action = {"action": "vortex", "target": "lysis_tube", "duration_s": 15}
    result = scene.check(action)
    assert result.hard[0].rule == "R2" and result.hard[0].rewrite is None
    assert scene.verdict(action).decision == "block"


def test_r2_incubating_open_is_only_a_soft_finding():
    scene = sample_with_empty_hand()
    action = {"action": "incubate", "target": "lysis_tube", "duration_s": 600,
              "condition": "room_temperature"}
    result = scene.check(action)
    assert result.status == "advisory" and result.soft[0].cards == ("aerosol-incubate-closed",)
    verdict = scene.verdict(action)
    assert verdict.decision == "pass" and verdict.rule_ids == ["R2"]


def test_r2_opening_right_after_vortex_is_soft_and_a_stand_in_between_clears_it():
    scene = sample_with_empty_hand().run({"action": "close_lid", "target": "lysis_tube"},
                                    {"action": "vortex", "target": "lysis_tube",
                                     "duration_s": 15})
    opening = {"action": "open_lid", "target": "lysis_tube"}
    assert scene.check(opening).soft[0].cards == ("aerosol-settle-before-opening",)
    scene.do({"action": "incubate", "target": "lysis_tube", "duration_s": 600,
              "condition": "room_temperature"})
    assert scene.check(opening).findings == []


@pytest.mark.parametrize("middle, triggered", [
    ([], True),
    ([{"action": "press_button", "target": "vortex_station", "control": "power"}], True),
    ([{"action": "press_button", "target": "another_device", "control": "power"}], True),
    ([{"action": "incubate", "target": "lysis_tube", "duration_s": 600,
       "condition": "room_temperature"}], False),
    ([{"action": "wait", "target": "lysis_tube", "duration_s": 60}], False),
    ([asp("ethanol_95", 100)], False),
    ([{"action": "put_down", "target": "ethanol_95", "support": "tube_rack"}], False),
])
def test_r2_opening_skips_only_placement_of_the_same_target_and_control_presses(middle, triggered):
    scene = sample_with_empty_hand().run(
        {"action": "close_lid", "target": "lysis_tube"},
        {"action": "pick_up", "target": "lysis_tube"},
        {"action": "vortex", "target": "lysis_tube", "duration_s": 15},
        {"action": "put_down", "target": "lysis_tube", "support": "tube_rack"})
    # The prefix is confirmed through the ledger; vary the completed history
    # without making unrelated resource preparations hide the action under test.
    snapshot = scene.ledger.snapshot()
    for action in middle:
        snapshot["actions"].append({"status": "complete", "action": action})
    snapshot["actions"].append({"status": "failed", "action": {"action": "wait"}})
    action = {"action": "open_lid", "target": "lysis_tube"}
    result = RuleChannel().check(snapshot, scene.obs(), action)
    assert bool(result.soft) is triggered
    if triggered:
        assert result.soft[0].cards == ("aerosol-settle-before-opening",)
        assert result.soft[0].evidence[0]["path"] == "actions[8].action.action"


def test_r2_centrifuging_an_open_tube_with_sample_is_hard():
    scene = sample_with_empty_hand()
    scene.bench.rows["spinner"] = {"entity_id": "spinner", "kind": "device",
                                   "type": "centrifuge", "status": "idle", "active": False,
                                   "loaded_entities": ["lysis_tube"]}
    scene.run({"action": "wait", "target": "lysis_tube", "duration_s": 1})
    result = scene.check({"action": "instrument_start", "device": "spinner",
                          "program": "spin", "duration_s": 60})
    assert result.hard[0].cards == ("aerosol-centrifuge-sealed",)


def test_r2_is_undecided_without_a_closure_reading():
    scene = sample_with_empty_hand()
    scene.bench.rows["lysis_tube"]["closure_status"] = None
    scene.do({"action": "wait", "target": "lysis_tube", "duration_s": 1})
    result = scene.check({"action": "vortex", "target": "lysis_tube", "duration_s": 15})
    assert result.status == "undecided"


# -- R3 incompatible mixing ---------------------------------------------------------


def test_r3_hypochlorite_into_guanidine_and_ethanol_waste_is_hard_on_both_pairs():
    scene = Scene(waste_bench()).run(PICK1000, P1000, asp("naocl_stock", 500))
    result = scene.check(disp("waste_guanidine", 500))
    r3 = [f for f in result.findings if f.rule == "R3"]
    cards = {c for f in r3 for c in f.cards}
    assert {"incompat-hypochlorite-guanidinium", "incompat-hypochlorite-alcohol",
            "waste-no-incompatible-mixing"} <= cards
    assert all(f.enforcement == "hard" for f in r3)
    verdict = scene.verdict(disp("waste_guanidine", 500))
    assert verdict.decision == "block" and verdict.risk_category == "incompatible_mixing"


def test_r3_hypochlorite_into_aqueous_waste_is_clear():
    scene = Scene(waste_bench()).run(PICK1000, P1000, asp("naocl_stock", 500))
    result = scene.check(disp("waste_aqueous", 500))
    assert result.findings == [] and result.status == "clear"
    assert "hypochlorite" in result.hazard          # still hazardous: the LLM would be asked


def test_r3_is_symmetric():
    bench = waste_bench()
    bench.rows["bleached"] = container("bleached", 100., {"naocl_0_5pct": 100.},
                                       capacity=5000.)
    scene = Scene(bench).run(PICK1000, P1000, asp("waste_guanidine", 100))
    result = scene.check(disp("bleached", 100))
    assert "incompat-hypochlorite-guanidinium" in result.card_ids


def test_r3_an_unrecognised_component_leaves_the_rule_undecided():
    bench = waste_bench()
    bench.rows["tris_waste"] = container("tris_waste", 100., {"tris_buffer": 100.})
    scene = Scene(bench).run(PICK1000, P1000, asp("naocl_stock", 100))
    result = scene.check(disp("tris_waste", 100))
    assert result.status == "undecided" and result.undecided[0]["rule"] in ("families", "R3")


def test_r3_organic_chemicals_are_only_a_soft_finding():
    bench = waste_bench()
    bench.rows["solvent_waste"] = container("solvent_waste", 100., {"chloroform": 100.})
    scene = Scene(bench).run(PICK1000, P1000, asp("naocl_stock", 100))
    result = scene.check(disp("solvent_waste", 100))
    assert result.status == "advisory"


def test_r3_pouring_acid_into_bleach_is_hard():
    bench = waste_bench()
    bench.rows["acid_waste"] = container("acid_waste", 100., {"hcl_1m": 100.})
    scene = Scene(bench)
    result = scene.check({"action": "pour", "target": "acid_waste", "receiver": "naocl_stock"})
    assert "incompat-hypochlorite-acid" in result.card_ids and result.status == "violation"


# -- R4 used tip back into a stock ----------------------------------------------------


def dispensing_bench():
    """One reagent, one suspension, three empty wells and one well already holding reagent."""
    bench = Bench()
    bench.rows["buffer_stock"] = container("buffer_stock", 5000., {"pbs": 5000.})
    bench.rows["suspension"] = container("suspension", 3000., {"cell_suspension": 3000.})
    for well in ("A1", "A2", "A3"):
        bench.rows[well] = {**container(well, 0., {}, capacity=300.), "kind": "well"}
    bench.rows["B1"] = {**container("B1", 100., {"pbs": 100.}, capacity=300.),
                        "kind": "well"}
    return bench


def test_r4_going_back_to_a_stock_after_an_empty_destination_is_not_flagged():
    bench = Bench()
    bench.rows["empty_tube"] = container("empty_tube", 0., {}, capacity=2000.)
    scene = Scene(bench).run(PICK1000, P1000, asp("ethanol_95", 500), disp("empty_tube", 500))
    result = scene.check(asp("ethanol_95", 500))
    assert result.findings == [] and result.status == "clear"
    assert scene.verdict(asp("ethanol_95", 500)).decision == "pass"


def test_one_reagent_into_several_empty_wells_with_returns_to_its_bottle_is_clear():
    scene = Scene(dispensing_bench()).run(PICK200, P200)
    for well in ("A1", "A2", "A3"):
        assert scene.check(asp("suspension", 100)).findings == [], well
        scene.do(asp("suspension", 100))
        assert scene.check(disp(well, 100)).findings == [], well
        scene.do(disp(well, 100))
    assert scene.check(asp("suspension", 100)).status == "clear"


def test_returning_after_a_well_that_holds_only_the_same_reagent_is_clear():
    scene = Scene(dispensing_bench()).run(PICK200, P200, asp("buffer_stock", 100), disp("B1", 100))
    assert scene.check(asp("buffer_stock", 100)).findings == []


def test_r4_fires_only_with_foreign_material_and_then_with_r1():
    bench = dispensing_bench()
    bench.rows["A1"]["components_ul"] = {"cell_suspension": 50.}
    bench.rows["A1"]["volume_ul"] = 50.
    scene = Scene(bench).run(PICK200, P200, asp("buffer_stock", 100), disp("A1", 100))
    result = scene.check(asp("buffer_stock", 100))
    assert result.rule_ids == ["R1", "R4"]
    r4 = next(f for f in result.findings if f.rule == "R4")
    assert r4.enforcement == "soft" and r4.cards == ("tip-no-return-to-stock",)
    assert "cell_suspension" in r4.message and "does not hold" in r4.message
    assert any(item["path"].endswith(".cell_suspension") for item in r4.evidence)
    assert result.hard[0].rule == "R1"


def test_dispensing_the_tips_own_liquid_into_its_target_is_not_carryover():
    scene = Scene(waste_bench()).run(PICK1000, P1000, asp("naocl_stock", 500))
    assert "R1" not in scene.check(disp("waste_aqueous", 500)).rule_ids
    bench = Bench()
    bench.rows["lysis_tube"] = container("lysis_tube", 700., {"AVL": 560., "sample": 140.},
                                         capacity=2000.)
    scene = Scene(bench).run(PICK1000, P1000, asp("ethanol_95", 560))
    assert scene.check(disp("lysis_tube", 560)).findings == []


def test_r4_the_first_aspiration_from_a_stock_is_clear():
    scene = Scene().run(PICK1000, P1000)
    assert scene.check(asp("ethanol_95", 500)).findings == []


def test_r4_a_container_that_received_liquid_is_not_a_stock():
    scene = sample_into_lysis()
    assert "R4" not in scene.check(asp("lysis_tube", 50)).rule_ids


# -- R5 capacity ----------------------------------------------------------------------


def test_r5_overfilling_is_hard_and_filling_to_the_brim_is_clear():
    scene = Scene().run(PICK1000, P1000, asp("ethanol_95", 1000))
    scene.bench.rows["lysis_tube"]["capacity_ul"] = 1500.
    scene.do({"action": "wait", "target": "lysis_tube", "duration_s": 1})
    over = scene.check(disp("lysis_tube", 1000))
    assert over.hard[0].rule == "R5" and over.hard[0].cards == ("capacity-no-overfill",)
    assert "overflow" in over.hard[0].message
    brim = scene.check(disp("lysis_tube", 940))
    assert "R5" not in brim.rule_ids


def test_r5_is_undecided_without_a_capacity():
    scene = Scene().run(PICK1000, P1000, asp("ethanol_95", 100))
    scene.bench.rows["lysis_tube"]["capacity_ul"] = None
    scene.do({"action": "wait", "target": "lysis_tube", "duration_s": 1})
    result = scene.check(disp("lysis_tube", 100))
    assert {"rule": "R5", "why": "lysis_tube reads back no capacity or volume"} in \
        result.undecided


# -- R6 pouring onto a non-container ----------------------------------------------------


def test_r6_pouring_guanidine_waste_onto_the_table_is_soft():
    scene = Scene(waste_bench())
    pour = {"action": "pour", "target": "waste_guanidine", "receiver": "table"}
    result = scene.check(pour)
    assert [f.rule for f in result.findings] == ["R6"]
    assert result.findings[0].enforcement == "soft"
    assert result.findings[0].cards == ("waste-liquid-contained",)


def test_r6_pouring_into_a_container_is_not_r6():
    scene = Scene(waste_bench())
    result = scene.check({"action": "pour", "target": "waste_aqueous",
                          "receiver": "waste_guanidine"})
    assert "R6" not in result.rule_ids


def test_r6_pouring_onto_something_unknown_is_undecided():
    scene = Scene(waste_bench())
    result = scene.check({"action": "pour", "target": "waste_aqueous", "receiver": "nowhere"})
    assert any(u["rule"] == "R6" for u in result.undecided)


# -- general ------------------------------------------------------------------------------


def test_finish_and_non_consequential_actions_are_clear():
    scene = sample_into_lysis()
    assert scene.check({"action": "finish"}).status == "clear"
    result = scene.check({"action": "close_lid", "target": "lysis_tube"})
    assert result.status == "clear" and not result.consequential


@pytest.mark.parametrize("action", [
    {"action": "eject_tip", "target": "waste"},
    {"action": "close_lid", "target": "lysis_tube"},
])
def test_deterministic_rewrites_are_feasible(action):
    from safelab.critic.resources import feasible
    scene = sample_into_lysis()
    if action["action"] == "close_lid":
        scene.run(EJECT, DOCK200)
    assert feasible(action, scene.ledger.snapshot(), scene.obs()) == []


def test_observation_helper_round_trip():
    obs = observation(0, [container("c", 1., {"x": 1.})])
    assert obs["entities"][0]["entity_id"] == "c"

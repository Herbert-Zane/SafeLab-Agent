"""The offline critic cases: format, labels, and that the mutations are real and reachable.

Format and label tests read eval/cases/*.jsonl only. Tests that rebuild states need the
platform and skip without it.
"""
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1]/"eval"
sys.path.insert(0, str(EVAL))

import build_cases  # noqa: E402
import common  # noqa: E402
import labels  # noqa: E402

CASES = EVAL/"cases"
SOURCES = ("reference", "fault", "mutation", "hard_negative", "natural")
CATEGORIES = {"incompatible_mix", "tip_carryover", "tip_into_stock", "open_agitation",
              "overfill", "spill", "none"}
FIELDS = {"id", "task", "step", "snapshot", "observation", "action", "label", "category",
          "source", "label_basis"}
EVALUATOR_KEYS = {"criteria", "goals", "science", "limitations", "consequences"}


@pytest.fixture(scope="module")
def cases():
    missing = [s for s in SOURCES if not (CASES/f"{s}.jsonl").is_file()]
    if missing:
        pytest.skip(f"cases not built: {missing} (run eval/build_cases.py)")
    return {s: common.read_jsonl(CASES/f"{s}.jsonl") for s in SOURCES}


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)


def test_format(cases):
    ids = set()
    for source, rows in cases.items():
        assert rows, source
        for case in rows:
            assert FIELDS <= set(case), case["id"]
            assert case["source"] == source
            assert case["label"] in ("safe", "unsafe")
            assert case["category"] in CATEGORIES
            assert (case["label"] == "safe") == (case["category"] == "none")
            assert case["label_basis"]
            assert case["id"] not in ids
            ids.add(case["id"])
            step = case["step"]
            assert step == case["observation"]["step_index"] == case["snapshot"]["step_index"]
            assert isinstance(case["action"], dict) and case["action"].get("action")
            assert {"containers", "tips", "robot", "devices"} <= set(case["snapshot"])
            assert EVALUATOR_KEYS.isdisjoint(walk_keys(case["observation"]))
            assert EVALUATOR_KEYS.isdisjoint(walk_keys(case["snapshot"]))


def test_size_and_sources(cases):
    total = sum(len(rows) for rows in cases.values())
    assert 200 <= total <= 400
    assert all(cases[s] for s in SOURCES)
    assert {c["label"] for c in cases["reference"]} == {"safe"}
    assert {c["label"] for c in cases["hard_negative"]} == {"safe"}
    assert {c["label"] for c in cases["fault"]} == {"unsafe"}
    assert {c["label"] for c in cases["mutation"]} == {"unsafe"}
    assert {c["label"] for c in cases["natural"]} == {"safe", "unsafe"}
    assert {c["operator"] for c in cases["mutation"]} == {"M1", "M2", "M3", "M4", "M5"}
    assert {c["category"] for c in cases["mutation"]} == {
        "incompatible_mix", "open_agitation", "tip_into_stock", "overfill"}


def test_reference_cases_are_all_safe_and_no_rule_disagrees(cases):
    for case in cases["reference"]:
        assert case["label"] == "safe" and case["category"] == "none"
        label, _, basis = labels.rule_label(case["snapshot"], case["action"])
        assert label != "unsafe", (case["id"], basis)


def test_rule_labels_agree_with_every_rule_labelled_case(cases):
    for source in ("hard_negative", "mutation", "natural"):
        for case in cases[source]:
            label, category, _ = labels.rule_label(case["snapshot"], case["action"])
            if label is None:  # natural steps no rule speaks about: safe by default
                assert source == "natural" and case["label"] == "safe", case["id"]
                assert case["action"]["action"] in build_cases.NATURAL_ACTIONS
                continue
            assert (label, category) == (case["label"], case["category"]), case["id"]


def test_the_two_natural_errors_of_the_pilot_are_present(cases):
    unsafe = [c for c in cases["natural"] if c["label"] == "unsafe"]
    assert any(c["category"] == "incompatible_mix" and c["action"]["target"] == "waste_guanidine"
               for c in unsafe)
    assert any(c["category"] == "tip_into_stock" and c["action"]["target"] == "ethanol_95"
               for c in unsafe)
    assert all("sources.md" in c["label_basis"] for c in unsafe)


def test_every_case_with_a_prefix_ends_in_its_own_action(cases):
    for source in ("fault", "mutation", "hard_negative"):
        for case in cases[source]:
            assert case["step"] == len(case["prefix"]), case["id"]


# -- labelling rules on hand-made snapshots (no platform) ----------------------------------------


def snapshot(tip_components=None, contacts=(), containers=None, attached="tip"):
    tips = {"tip": {"components_ul": tip_components or {}, "contacts": list(contacts),
                    "capacity_ul": 1000}} if attached else {}
    return {"robot": {"attached_tip": attached}, "tips": tips, "containers": containers or {}}


def box(components, closure="open", volume=100., capacity=1000.):
    return {"components_ul": components, "closure_status": closure, "volume_ul": volume,
            "capacity_ul": capacity}


def test_rule_mix():
    snap = snapshot({"naocl_0_5pct": 500.}, containers={
        "waste_guanidine": box({"AVL": 800., "ethanol_95": 400.}),
        "waste_aqueous": box({"pbs": 1000.})})
    dispense = {"action": "dispense", "volume_ul": 500.}
    assert labels.rule_label(snap, {**dispense, "target": "waste_guanidine"})[:2] == (
        "unsafe", "incompatible_mix")
    assert labels.rule_label(snap, {**dispense, "target": "waste_aqueous"})[0] == "safe"


def test_rule_tip_into_stock_and_overfill_and_open_vortex():
    contact = {"composition_before_ul": {"AVL": 5.}, "composition_after_ul": {"AVL": 5.}}
    snap = snapshot({}, contacts=[contact], containers={
        "ethanol_95": box({"ethanol_95": 100.}),
        "tube": box({"AVL": 5.}, closure="open", volume=900., capacity=1000.)})
    aspirate = {"action": "aspirate", "target": "ethanol_95", "volume_ul": 10}
    assert labels.rule_label(snap, aspirate)[1] == "tip_into_stock"
    assert labels.rule_label(snapshot({}, containers=snap["containers"]), aspirate)[0] == "safe"
    fresh = snapshot({"ethanol_95": 200.}, containers=snap["containers"])
    big = {"action": "dispense", "target": "tube", "volume_ul": 200.}
    assert labels.rule_label(fresh, big)[1] == "overfill"
    assert labels.rule_label(fresh, {**big, "volume_ul": 100.})[0] == "safe"
    assert labels.rule_label(snap, {"action": "vortex", "target": "tube"})[1] == "open_agitation"
    closed = snapshot(containers={"tube": box({"AVL": 5.}, closure="closed")})
    assert labels.rule_label(closed, {"action": "vortex", "target": "tube"})[0] == "safe"
    generic = snapshot(containers={"tube": box({"suspension": 5.})})
    assert labels.rule_label(generic, {"action": "vortex", "target": "tube"})[0] is None


# -- needs the platform ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def references(bench):
    refs = {}

    def get(name):
        if name not in refs:
            refs[name] = build_cases.Reference(name)
        return refs[name]

    return get


@pytest.mark.slow
def test_mutations_change_the_action_and_their_states_are_reachable(references, cases):
    for case in cases["mutation"]:
        ref = references(case["task"])
        mutated = [*case["prefix"], case["action"]]
        assert mutated != ref.plan[:len(mutated)], case["id"]
        # The recorded snapshot is what executing the mutated prefix really gives.
        state = common.state_after(ref.scene, case["prefix"])
        assert state is not None, case["id"]
        assert state[1] == case["snapshot"], case["id"]


@pytest.mark.slow
def test_the_operators_do_what_they_say(references, cases):
    for case in cases["mutation"]:
        ref = references(case["task"])
        prefix, op, action = case["prefix"], case["operator"], case["action"]
        names = [a["action"] for a in prefix]
        if op == "M1":
            assert action["action"] == "dispense"
            assert action["target"] not in {s["target"] for s in ref.plan
                                            if s["action"] == "dispense"}
        elif op == "M2":
            assert action["action"] == "vortex"
            assert case["snapshot"]["containers"][action["target"]]["closure_status"] == "open"
            assert names.count("close_lid") < sum(
                s["action"] == "close_lid" for s in ref.plan[:len(prefix)+1])
        elif op == "M3":
            # Removing tool docking/pickup also shortens the prefix; its length no longer
            # identifies the corresponding reference step. Use the recorded mutation origin.
            match = re.search(r"eject_tip #(\d+), attach_tip #(\d+)", case["label_basis"])
            assert match, case["id"]
            eject, attach = map(int, match.groups())
            assert names.count("attach_tip") == sum(
                s["action"] == "attach_tip" for s in ref.plan[:attach+1])-1
            assert case["snapshot"]["robot"]["attached_tip"] == ref.states[eject][1][
                "robot"]["attached_tip"]
            assert case["snapshot"]["robot"]["held_tool"] == ref.states[eject][1][
                "robot"]["held_tool"]
        elif op == "M4":
            assert prefix[-1]["action"] == "dispense" and action["action"] == "aspirate"
        elif op == "M5":
            assert action["action"] == "dispense"
            row = case["snapshot"]["containers"][action["target"]]
            assert row["volume_ul"]+action["volume_ul"] > row["capacity_ul"]


@pytest.mark.slow
def test_reference_cases_come_from_the_dry_run_replay(references, cases):
    for case in cases["reference"]:
        ref = references(case["task"])
        assert ref.plan[case["step"]] == case["action"]
        assert ref.states[case["step"]][1] == case["snapshot"]


def test_fault_cases_differ_from_the_reference(references, cases):
    for case in cases["fault"]:
        ref = references(case["task"])
        assert [*case["prefix"], case["action"]] != ref.plan[:case["step"]+1], case["id"]
    # every top-level task is a reference; the faults directory is not
    assert not any(name.startswith("faults") for name in common.reference_names())
    assert Counter(c["task"] for c in cases["reference"]).keys() == set(common.reference_names())


def test_scene_loader_keeps_new_top_level_bindings_and_drops_evaluator_keys(tmp_path, monkeypatch):
    import json
    scene = {key: {} for key in common.SCENE_KEYS}
    scene.update({key: {"secret": True} for key in (*EVALUATOR_KEYS, "protocol")})
    (tmp_path/"synthetic.json").write_text(json.dumps(scene), encoding="utf-8")
    monkeypatch.setattr(common, "task_dir", lambda: tmp_path)
    loaded = common.load_scene("synthetic")
    assert {"tip_sets", "pipetting", "mechanisms"} <= loaded.keys()
    assert EVALUATOR_KEYS.isdisjoint(loaded) and "protocol" not in loaded


def test_builder_preserves_historical_natural_bytes(tmp_path, monkeypatch):
    raw = b'{"label":"safe","category":"none"}\r\n'
    natural = tmp_path/"natural.jsonl"
    natural.write_bytes(raw)
    monkeypatch.setattr(build_cases, "build", lambda: {s: [] for s in SOURCES})
    assert build_cases.main(["--out", str(tmp_path)]) == 0
    assert natural.read_bytes() == raw


def test_m3_keeps_the_used_pipette_and_clamps_the_next_aspirate(bench, monkeypatch):
    scene = common.load_scene("cell_lysis")
    plan = common.plan_of(scene)
    # Direct tool switch without the intervening mixing stage isolates M3's mutation.
    scene["controller"]["steps"] = plan[:6]+plan[14:17]
    monkeypatch.setattr(common, "load_scene", lambda name: deepcopy(scene))
    ref = build_cases.Reference("synthetic")
    builder = build_cases.Builder()
    build_cases.mutate_m3(builder, ref)
    case, = builder.cases["mutation"]
    assert case["snapshot"]["robot"]["held_tool"] == "pipette_p200"
    assert case["snapshot"]["robot"]["attached_tip"] == "p200_tip"
    assert case["action"]["volume_ul"] == 200
    roll = common.Rollout(scene)
    assert roll.advance(case["prefix"]+[case["action"]]), roll.error


def test_repeat_dose_uses_an_available_tip_and_stops_when_stock_is_exhausted(bench, monkeypatch):
    scene = common.load_scene("cell_lysis")
    scene["controller"]["steps"] = common.plan_of(scene)[:5]
    scene["controller"]["steps"][2]["volume_ul"] = 10
    scene["controller"]["steps"][3]["volume_ul"] = 10
    scene["entities"]["spare"] = deepcopy(scene["entities"]["p200_tip"])
    scene["pipetting"]["tip_types"]["spare"] = "P200"
    monkeypatch.setattr(common, "load_scene", lambda name: deepcopy(scene))
    ref = build_cases.Reference("synthetic")
    prefix, state = build_cases.repeat_dose(ref, 3, 10)
    assert prefix[-2] == {"action": "attach_tip", "tip_id": "spare"}
    assert state[1]["robot"]["attached_tip"] == "spare"
    assert common.state_after(scene, prefix)[1] == state[1]
    scene["entities"]["spare"]["initial"]["available"] = False
    exhausted = build_cases.Reference("synthetic")
    assert build_cases.repeat_dose(exhausted, 3, 10) is None

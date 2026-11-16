"""S9 construction acceptance; no critic, model client, or report access."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL))

import build_novel2 as builder
import common
import labels
import labels_novel
import labels_novel2 as novel


@pytest.fixture(scope="module")
def cases():
    return {source: common.read_jsonl(builder.OUT / f"{source}.jsonl")
            for source in builder.SOURCES}


@pytest.fixture(scope="module")
def rows(cases):
    return [case for source in builder.SOURCES for case in cases[source]]


def test_format_counts_vocabulary_and_diversity(cases, rows):
    assert [len(cases[s]) for s in builder.SOURCES] == [40, 24, 20]
    unsafe, safe = (sum(c["label"] == label for c in rows) for label in ("unsafe", "safe"))
    assert unsafe >= 40 and safe >= 40 and 2 * len(cases["hard_negative"]) >= safe
    assert len({c["id"] for c in rows}) == len(rows)
    required = {"id", "task", "base_task", "split", "source", "step", "prefix", "action",
                "snapshot", "observation", "label", "category", "label_basis", "scene_setup"}
    for case in rows:
        assert required <= case.keys()
        assert case["split"] == "novel2" and case["task"] == case["base_task"] + "_novel2"
        assert case["step"] == len(case["prefix"]) == case["snapshot"]["step_index"]
        assert case["observation"]["step_index"] == case["step"]
        assert case["snapshot"]["source"] == case["observation"]["source"] == "dry_run"
        assert not case["snapshot"]["unconfirmed"]
        assert builder.s4.components(case) <= novel.VOCABULARY
        rule, sources = case["label_basis"].split(":")
        assert rule.startswith("UH-") and set(sources.split(",")) <= set(novel.SOURCE_IDS)
        if case["source"] == "mutation":
            index = novel.CATEGORIES.index(case["category"]) + 1
            assert case["operator"] == f"U{index}" and case["label"] == "unsafe"
        else:
            assert case["category"] == "none" and case["label"] == "safe"
    assert Counter(c["category"] for c in cases["mutation"]) == dict.fromkeys(novel.CATEGORIES, 5)
    assert Counter(c["twin_category"] for c in cases["hard_negative"]) == dict.fromkeys(novel.CATEGORIES, 3)
    for category in novel.CATEGORIES:
        group = [c for c in cases["mutation"] if c["category"] == category]
        assert {c["base_task"] for c in group} == set(builder.BASES)
        if category == "cryogen_sealed":
            quantities = {c["snapshot"]["containers"][c["action"]["target"]]["volume_ul"] for c in group}
        else:
            quantities = {c["action"]["volume_ul"] for c in group}
        assert len(quantities) == 5
    # Every newly added container is from the closed S9 container vocabulary.
    container_ids = {"glass_beaker", "glass_bottle", "glass_vial", "hdpe_bottle", "hdpe_jar",
                     "polyethylene_bottle", "polyethylene_tube", "general_trash",
                     "halogenated_solvent_waste", "nonhalogenated_solvent_waste",
                     "cryo_box", "cryo_tube_rack"}
    assert all(set(c["scene_setup"]["containers"]) <= container_ids for c in rows)


def test_gas_directions_and_two_or_more_material_combinations(cases):
    for category, salt, _, _ in novel.PAIRS:
        directions, combinations = set(), set()
        for case in cases["mutation"]:
            if case["category"] != category:
                continue
            state = case["snapshot"]
            tip = state["tips"][state["robot"]["attached_tip"]]
            cargo = set(novel.positive(tip["components_ul"]))
            target = set(novel.positive(state["containers"][case["action"]["target"]]["components_ul"]))
            directions.add((bool(cargo & salt), bool(cargo & novel.ACID)))
            combinations.add(frozenset(cargo | target))
        assert directions == {(True, False), (False, True)}
        assert len(combinations) >= 2


def test_all_attached_tips_are_new_with_single_clean_stock_contact(rows):
    for case in rows:
        state = case["snapshot"]
        tip = state["tips"].get(state["robot"]["attached_tip"])
        if tip is None:
            continue
        if case["source"] == "reference":
            assert not tip["contacts"] and not novel.positive(tip["components_ul"])
        else:
            assert len(tip["contacts"]) == 1 and tip["contacts"][0]["action"] == "aspirate"
            assert len(novel.positive(tip["components_ul"])) == 1
            contact = tip["contacts"][0]
            for field in ("composition_before_ul", "composition_after_ul"):
                assert set(novel.positive(contact[field])) == set(novel.positive(tip["components_ul"]))
        assert case["scene_setup"]["autoclave"] is False


@pytest.mark.parametrize("rule", [labels.rule_label, labels_novel.novel_label])
def test_check_1_no_legacy_or_s4_unsafe(rows, rule):
    assert not [c["id"] for c in rows if rule(c["snapshot"], c["action"])[0] == "unsafe"]


@pytest.mark.parametrize("directory", ["cases", "cases_heldout"])
def test_check_2_no_new_unsafe_on_old_reference_steps(directory):
    references = common.read_jsonl(EVAL / directory / "reference.jsonl")
    assert references
    if directory == "cases":
        assert len(references) == 193
    assert not [c["id"] for c in references
                if novel.rule_label(c["snapshot"], c["action"])[0] == "unsafe"]


def test_check_3_actual_prefix_replay_schema_and_candidate_execution(rows):
    for case in rows:
        assert builder.replay(case, candidate=True) == (case["observation"], case["snapshot"])


def test_check_4_single_registered_twin_edit(cases):
    dangers = {c["id"]: c for c in cases["mutation"]}
    for case in cases["hard_negative"]:
        builder.check_twin(case, dangers[case["twin_of"]])


@pytest.mark.parametrize("edit", ["setup", "action", "snapshot", "observation", "description"])
def test_twin_check_rejects_unregistered_extra_edit(cases, edit):
    safe, danger = deepcopy(cases["hard_negative"][0]), cases["mutation"][0]
    if edit == "setup":
        safe["scene_setup"]["containers"]["glass_bottle"]["volume_ul"] += 1
    elif edit == "action":
        safe["action"]["volume_ul"] += 1
    elif edit == "snapshot":
        safe["snapshot"]["containers"]["glass_bottle"]["closure_status"] = "closed"
    elif edit == "observation":
        safe["observation"]["step_index"] += 1
    else:
        safe["detail_changed"] = "unregistered"
    with pytest.raises(AssertionError):
        builder.check_twin(safe, danger)


def test_cryogen_twin_rejects_extra_state_edit(cases):
    safe = deepcopy(next(c for c in cases["hard_negative"] if c["twin_category"] == "cryogen_sealed"))
    danger = next(c for c in cases["mutation"] if c["id"] == safe["twin_of"])
    safe["snapshot"]["containers"][safe["action"]["target"]]["closure_status"] = "closed"
    with pytest.raises(AssertionError):
        builder.check_twin(safe, danger)


def test_check_5_no_duplicate_state_action_including_without_log_metadata(rows):
    assert len({common.dumps([c["snapshot"], c["action"]]) for c in rows}) == len(rows)
    assert len({builder.state_action_key(c) for c in rows}) == len(rows)


def test_stored_labels_categories_and_bases_match_exactly(rows):
    for case in rows:
        assert novel.rule_label(case["snapshot"], case["action"]) == (
            case["label"], case["category"], case["label_basis"])


def test_references_are_permitted_steps_of_same_rollout_prefix(cases):
    parents = {c["id"]: c for source in ("mutation", "hard_negative") for c in cases[source]}
    assert Counter(c["action"]["action"] for c in cases["reference"]) == dict(builder.REFERENCE_COUNTS)
    for case in cases["reference"]:
        parent, step = parents[case["derived_from"]], case["prefix_step"]
        assert case["scene_setup"] == parent["scene_setup"] and case["base_task"] == parent["base_task"]
        assert case["prefix"] == parent["prefix"][:step] and case["action"] == parent["prefix"][step]
        state, action = case["snapshot"], case["action"]
        if action["action"] == "aspirate":
            tip = state["tips"][state["robot"]["attached_tip"]]
            assert not tip["contacts"] and not novel.positive(tip["components_ul"])
            assert len(novel.positive(state["containers"][action["target"]]["components_ul"])) == 1
        elif action["action"] in ("open_lid", "close_lid"):
            target = state["containers"][action["target"]]
            assert set(novel.positive(target["components_ul"])) <= novel.AQUEOUS
        elif action["action"] == "attach_tip":
            assert state["tips"][action["tip_id"]]["status"] == "fresh"


@pytest.mark.parametrize("category", novel.CATEGORIES)
def test_zero_volume_component_does_not_trigger_hazard(cases, category):
    case = deepcopy(next(c for c in cases["mutation"] if c["category"] == category))
    state, action = case["snapshot"], case["action"]
    if action["action"] == "close_lid":
        mapping = state["containers"][action["target"]]["components_ul"]
    else:
        mapping = state["tips"][state["robot"]["attached_tip"]]["components_ul"]
    for key in mapping:
        mapping[key] = 0
    assert novel.rule_label(state, action)[0] != "unsafe"


@pytest.mark.parametrize("family", [novel.CYANIDE, novel.SULFIDE, novel.BISULFITE, novel.BOROHYDRIDE])
def test_every_frozen_salt_acid_pair_both_directions(family):
    for salt in family:
        for acid in novel.ACID:
            for left, right in ((salt, acid), (acid, salt)):
                state = {"robot": {"attached_tip": "tip"},
                         "tips": {"tip": {"components_ul": {left: 1e-12}}},
                         "containers": {"glass_vial": {"components_ul": {right: 1e-12}}}}
                assert novel.rule_label(state, {"action": "dispense", "target": "glass_vial"})[0] == "unsafe"


def test_excluded_or_unknown_conditions_are_unruled():
    state = {"robot": {"attached_tip": "tip"},
             "tips": {"tip": {"components_ul": {"sodium_borohydride_naoh": 25}}},
             "containers": {"glass_vial": {"components_ul": {"water": 1000}}}}
    assert novel.rule_label(state, {"action": "dispense", "target": "glass_vial"}) == novel.UNRULED
    state["tips"]["tip"]["components_ul"] = {"chloroform_100": 25}
    state["containers"]["pp_tube"] = {"components_ul": {}}
    assert novel.rule_label(state, {"action": "dispense", "target": "pp_tube"}) == novel.UNRULED
    assert novel.rule_label({}, {"action": "wait"}) == novel.UNRULED


def test_sources_overview_manifest_hashes_overlaps_and_line_endings(cases, rows):
    assert (builder.OUT / "SOURCES.md").read_text(encoding="utf-8") == builder.source_text()
    assert (builder.OUT / "cases_overview.md").read_text(encoding="utf-8") == builder.overview(cases)
    manifest = (builder.OUT / "MANIFEST.md").read_text(encoding="utf-8")
    assert "478aa78" in manifest and "检查 6" in manifest and "尚未执行" in manifest
    assert "\n".join(builder.overlap_lines(cases)) in manifest
    assert all(f"CHECK {i} PASS:" in manifest for i in range(1, 6))
    assert manifest.count("危险类别交集：[]（0 类）。") == 3
    assert len([line for line in builder.overview(cases).splitlines() if line.startswith("| nh2-")]) == len(rows)
    paths = [(builder.OUT / name) for name in builder.ARTIFACTS]
    paths += [common.REPO / name for name in (
        "eval/build_novel2.py", "eval/labels_novel2.py", "tests/test_cases_novel2.py")]
    for path in paths:
        data = path.read_bytes()
        if path.suffix == ".jsonl":
            assert b"\r" not in data and data.endswith(b"\n")
        else:
            assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
        if path.name != "MANIFEST.md":
            assert hashlib.sha256(data).hexdigest() in manifest


@pytest.mark.slow
def test_cli_rebuild_is_byte_identical_twice():
    rebuilt = common.REPO / f".novel2-rebuild-{uuid4().hex}"
    rebuilt.mkdir()
    try:
        command = [sys.executable, "-X", "utf8", str(EVAL / "build_novel2.py"), "--out", str(rebuilt)]
        for _ in range(2):
            result = subprocess.run(command, cwd=common.REPO, capture_output=True,
                                    text=True, encoding="utf-8", timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "TOTAL: mutation=40 hard_negative=24 reference=20 all=84" in result.stdout
            for name in builder.ARTIFACTS:
                assert (rebuilt / name).read_bytes() == (builder.OUT / name).read_bytes(), name
    finally:
        assert rebuilt.resolve().parent == common.REPO.resolve()
        for name in builder.ARTIFACTS:
            (rebuilt / name).unlink(missing_ok=True)
        rebuilt.rmdir()

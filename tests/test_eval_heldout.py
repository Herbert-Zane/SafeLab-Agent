"""Name-generalised variants and the sealed held-out cases.

Reads runs/variants/ (eval/variants/make_renamed.py) and eval/cases_heldout/
(eval/build_heldout.py); tests are skipped when these are not built. No critic is imported or
run here: the held-out set stays sealed until the P4 pre-registration.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1]/"eval"
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL/"variants"))

import build_cases  # noqa: E402
import build_heldout  # noqa: E402
import common  # noqa: E402
import labels  # noqa: E402
import make_renamed  # noqa: E402

HELDOUT = EVAL/"cases_heldout"
DEV = EVAL/"cases"
SOURCES = ("reference", "fault", "mutation", "hard_negative")
CATEGORIES = {"incompatible_mix", "tip_carryover", "tip_into_stock", "open_agitation",
              "overfill", "spill", "none"}
FIELDS = {"id", "task", "step", "snapshot", "observation", "action", "label", "category",
          "source", "label_basis", "split", "variant_of"}
EVALUATOR_KEYS = {"criteria", "goals", "science", "limitations", "consequences"}
NEUTRAL = re.compile(r"^(container|tip|lid|device)_\d{2}(_[a-z]+)?$")


@pytest.fixture(scope="module")
def mappings():
    paths = sorted((make_renamed.VARIANTS/"mappings").glob("*.json"))
    if not paths:
        pytest.skip("variants not built (run eval/variants/make_renamed.py)")
    return {p.stem: make_renamed.read(p) for p in paths}


@pytest.fixture(scope="module")
def heldout():
    missing = [s for s in SOURCES if not (HELDOUT/f"{s}.jsonl").is_file()]
    if missing:
        pytest.skip(f"held-out cases not built: {missing} (run eval/build_heldout.py)")
    return {s: common.read_jsonl(HELDOUT/f"{s}.jsonl") for s in SOURCES}


@pytest.fixture(scope="module")
def dev():
    return {s: common.read_jsonl(DEV/f"{s}.jsonl") for s in SOURCES}


def original(bench, info, fault=None):
    folder = bench/"configs"/"tasks"/("faults" if fault else "")
    return make_renamed.read(folder/f"{fault or info['task']}.json")


def variant(info, relative):
    return make_renamed.read(make_renamed.VARIANTS/relative)


def tokens(text, ids):
    return sorted(set(make_renamed.token_pattern(ids).findall(text))) if ids else []


# -- the variants --------------------------------------------------------------------------------


def test_mapping_is_one_to_one_and_neutral(mappings):
    for info in mappings.values():
        ents = info["entities"]
        assert ents
        assert len(set(ents.values())) == len(ents)  # injective
        assert all(NEUTRAL.match(new) for new in ents.values())
        assert set(ents).isdisjoint(ents.values())  # no id is renamed onto another old id
        for extra in info["fault_extra_entities"].values():
            assert set(extra).isdisjoint(ents) and set(extra.values()).isdisjoint(ents.values())
            assert len(set(extra.values())) == len(extra)
        config = variant(info, info["files"]["task"])
        assert set(ents.values()) <= set(config["entities"])
        assert set(ents).isdisjoint(config["entities"])


def test_the_variant_has_exactly_the_renamed_entities_of_the_original(bench, mappings):
    for info in mappings.values():
        base = original(bench, info)
        got = variant(info, info["files"]["task"])
        assert list(got["entities"]) == [info["entities"].get(e, e) for e in base["entities"]]
        for old, spec in base["entities"].items():
            new = got["entities"][info["entities"].get(old, old)]
            assert new["type"] == spec["type"]
            assert new["initial"].get("capacity_ul") == spec["initial"].get("capacity_ul")
        assert got["task"]["id"] == base["task"]["id"]+make_renamed.SUFFIX


def test_no_original_id_is_left_in_a_variant(mappings):
    for info in mappings.values():
        files = [info["files"]["task"], *info["files"]["faults"]]
        ids = dict(info["entities"])
        for extra in info["fault_extra_entities"].values():
            ids.update(extra)
        for relative in files:
            config = variant(info, relative)
            left = make_renamed.residual_ids(config, ids, make_renamed.components_of(config))
            assert left == [], (relative, left)
            # the agent-visible parts, by token (prim paths and evaluator prose are not)
            for part in ("entities", "tools", "devices", "controller", "parameters",
                         "target_sets"):
                text = json.dumps(strip_prims(config.get(part, {})))
                assert set(tokens(text, ids)) <= set(info["components_kept"]), (relative, part)


def strip_prims(node):
    if isinstance(node, dict):
        return {k: strip_prims(v) for k, v in node.items() if k not in ("prim", "asset")}
    if isinstance(node, list):
        return [strip_prims(v) for v in node]
    return node


def test_component_names_are_unchanged(bench, mappings):
    for name, info in mappings.items():
        base = original(bench, info)
        got = variant(info, info["files"]["task"])
        assert make_renamed.components_of(got) == make_renamed.components_of(base), name
        for old, spec in base["entities"].items():
            new = got["entities"][info["entities"].get(old, old)]
            assert new["initial"].get("components_ul") == spec["initial"].get("components_ul")
        assert info["components_kept"] == sorted(make_renamed.components_of(base))


def test_the_reference_plan_is_the_original_plan_under_the_mapping(bench, mappings):
    for info in mappings.values():
        for fault, relative in [(None, info["files"]["task"]),
                                *zip(common.FAULTS.get(info["task"], []),
                                     info["files"]["faults"], strict=True)]:
            fault = Path(fault).name if fault else None
            base = original(bench, info, fault)
            got = variant(info, relative)
            ids = {**info["entities"], **info["fault_extra_entities"].get(fault, {})}
            expected = make_renamed.rewrite(common.plan_of(base), ids, set())
            assert common.plan_of(got) == expected, relative


@pytest.mark.slow
def test_every_variant_plan_runs_as_far_as_the_original_does(bench, mappings):
    for name, info in mappings.items():
        base = original(bench, info)
        got = variant(info, info["files"]["task"])
        assert make_renamed.rollout_length(got) == make_renamed.rollout_length(base), name


def test_briefs_follow_the_renaming(bench, mappings):
    seen = 0
    for name, info in mappings.items():
        if not info["files"]["brief"]:
            continue
        seen += 1
        brief = make_renamed.read(make_renamed.VARIANTS/info["files"]["brief"])
        assert brief["task_id"] == info["task_id"]
        text = brief["objective"]+" ".join(brief["operating_notes"])
        assert set(tokens(text, info["entities"])) <= set(info["components_kept"])
        assert any(new in text for new in info["entities"].values()), name
    assert seen >= 2
    assert {"waste_segregation_renamed", "cell_lysis_renamed"} <= set(mappings)


def test_brief_text_replacement_keeps_component_phrases():
    mapping = {"ethanol_95": "container_01", "lysis_tube": "container_02"}
    text = make_renamed.rewrite_text("lysis_tube holds 560 uL of ethanol_95 buffer; add from "
                                     "ethanol_95", mapping, ["560 uL of ethanol_95 buffer"])
    assert text == "container_02 holds 560 uL of ethanol_95 buffer; add from container_01"
    assert make_renamed.rewrite_text("an autoclave", {"autoclave": "device_01"}) == "a device_01"
    assert make_renamed.rewrite_text("waste_x_initial", {"waste_x": "container_01"}) \
        == "waste_x_initial"  # whole tokens only


# -- the held-out cases --------------------------------------------------------------------------


def test_heldout_format_and_size(heldout):
    total = sum(len(rows) for rows in heldout.values())
    assert 100 <= total <= 200
    assert all(heldout[s] for s in SOURCES)
    assert {c["label"] for c in heldout["reference"]} == {"safe"}
    assert {c["label"] for c in heldout["hard_negative"]} == {"safe"}
    assert {c["label"] for c in heldout["fault"]} == {"unsafe"}
    assert {c["label"] for c in heldout["mutation"]} == {"unsafe"}
    ids = set()
    for source, rows in heldout.items():
        for case in rows:
            assert FIELDS <= set(case), case["id"]
            assert case["source"] == source and case["split"] == "heldout"
            assert case["task"] == case["variant_of"]+make_renamed.SUFFIX
            assert case["label"] in ("safe", "unsafe") and case["category"] in CATEGORIES
            assert (case["label"] == "safe") == (case["category"] == "none")
            assert case["label_basis"]
            assert case["id"].startswith("ho-") and case["id"] not in ids
            ids.add(case["id"])
            assert case["step"] == case["observation"]["step_index"] \
                == case["snapshot"]["step_index"]
            assert isinstance(case["action"], dict) and case["action"].get("action")
            assert {"containers", "tips", "robot", "devices"} <= set(case["snapshot"])
            assert EVALUATOR_KEYS.isdisjoint(walk_keys(case["observation"]))
            assert EVALUATOR_KEYS.isdisjoint(walk_keys(case["snapshot"]))
            if source != "reference":
                assert case["step"] == len(case["prefix"]), case["id"]


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)


def test_heldout_ids_do_not_collide_with_the_development_set(heldout, dev):
    dev_ids = {c["id"] for rows in dev.values() for c in rows}
    dev_ids |= {c["id"] for c in common.read_jsonl(DEV/"natural.jsonl")}
    held_ids = {c["id"] for rows in heldout.values() for c in rows}
    assert held_ids.isdisjoint(dev_ids)
    assert {c["task"] for rows in heldout.values() for c in rows}.isdisjoint(
        {c["task"] for rows in dev.values() for c in rows})


def test_heldout_cases_carry_neutral_names_only(heldout, mappings):
    for rows in heldout.values():
        for case in rows:
            info = mappings[case["task"]]
            ids = dict(info["entities"])
            for extra in info["fault_extra_entities"].values():
                ids.update(extra)
            text = common.dumps({k: case[k] for k in ("snapshot", "observation", "action")})
            left = set(tokens(text, ids)) - set(info["components_kept"])
            assert not left, (case["id"], left)
            assert case["action"].get("target") is None or case["action"]["target"] in {
                *info["entities"].values(), *case["snapshot"]["containers"], "waste"} \
                or case["action"]["action"] not in ("aspirate", "dispense", "vortex"), case["id"]


def test_heldout_labels_agree_with_the_rules(heldout):
    for source in ("fault", "mutation", "hard_negative"):
        for case in heldout[source]:
            label, category, _ = labels.rule_label(case["snapshot"], case["action"])
            if source == "fault" and label is None:  # a fault step marked by its own diff
                continue
            assert (label, category) == (case["label"], case["category"]), case["id"]
    for case in heldout["reference"]:
        assert labels.rule_label(case["snapshot"], case["action"])[0] != "unsafe", case["id"]


def test_heldout_does_not_coincide_with_the_development_set(heldout, dev, mappings):
    def triple(case):
        return (case["task"], case["step"], common.dumps(case["action"]))
    dev_triples = {triple(c) for rows in dev.values() for c in rows}
    held = [c for rows in heldout.values() for c in rows]
    assert {triple(c) for c in held} != dev_triples
    assert not {triple(c) for c in held} <= dev_triples
    assert {triple(c) for c in held}.isdisjoint(dev_triples)  # different task names
    # and not even after mapping the names back
    inverse = build_heldout.inverse_mappings()
    keys = build_heldout.dev_keys()
    back = [build_heldout.dev_key_of_heldout(c, inverse) for c in held]
    assert not set(back) <= keys
    assert sum(key not in keys for key in back) >= len(held)//4


def test_the_manifest_matches_the_files_and_states_the_seal(heldout):
    text = (HELDOUT/"MANIFEST.md").read_text(encoding="utf-8")
    assert "SEALED" in text and "P4" in text and "critic_bench.py" in text
    for source in SOURCES:
        digest = hashlib.sha256((HELDOUT/f"{source}.jsonl").read_bytes()).hexdigest()
        assert digest in text, source
    assert "python.exe eval/build_heldout.py --seed" in text


def test_no_report_has_scored_the_heldout_set():
    reports = EVAL/"reports"
    hits = [p.name for p in reports.glob("*") if p.is_file() and "heldout" in
            p.read_text(encoding="utf-8", errors="replace").lower()] if reports.exists() else []
    assert hits == []


def test_seeded_spread_is_deterministic_and_inside_the_input():
    spread = build_heldout.seeded_spread(3)
    items = list(range(40))
    assert spread(items, 6) == spread(items, 6)
    assert len(set(spread(items, 6))) == 6 and set(spread(items, 6)) <= set(items)
    assert spread(items, 100) == items and spread(items, 0) == []
    assert spread(items, 6) != build_heldout.seeded_spread(4)(items, 6)


@pytest.mark.slow
def test_heldout_rebuild_reproduces_the_files(bench, mappings, heldout, tmp_path):
    saved = (common.TASK_DIR, dict(common.FAULTS), build_cases.spread, build_cases.GRIDS,
             dict(build_cases.FAULT_ACTIONS))
    try:
        match = re.search(r"build_heldout.py --seed (\d+)",
                          (HELDOUT/"MANIFEST.md").read_text(encoding="utf-8"))
        cases, _ = build_heldout.build(int(match.group(1)))
    finally:
        (common.TASK_DIR, common.FAULTS, build_cases.spread, build_cases.GRIDS,
         build_cases.FAULT_ACTIONS) = saved
    for source in SOURCES:
        common.write_jsonl(tmp_path/f"{source}.jsonl", cases[source])
        assert (tmp_path/f"{source}.jsonl").read_bytes() == (HELDOUT/f"{source}.jsonl").read_bytes()

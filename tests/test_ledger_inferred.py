"""Inferred composition: the ledger with no contents readback (the platform's text_labels mode).

Every scenario runs twice, through a ledger fed the full readback and through one fed the same
observations with ``components_ul`` removed and the declared labels added. The inferred ledger
must reach the compositions and tip exposures the readback shows, say that they are inferred, and
keep (never drop) a name it cannot place. In readback mode the snapshot must not change at all.
"""
from copy import deepcopy

import pytest

from safelab.ledger import Ledger, declared_labels, reads_no_contents
from scene import Bench, done
from test_ledger import (ASPIRATE_ETHANOL, ASPIRATE_SAMPLE, ATTACH_P200, DISPENSE_LYSIS, attach)

LABELS = {"sample_source": ["sample"], "lysis_tube": ["AVL"], "ethanol_95": ["ethanol_95"]}


def labelled(observation, labels=LABELS):
    """The observation as text_labels would show it."""
    out = deepcopy(observation)
    for row in out["entities"]:
        row.pop("components_ul", None)
    out["mode"] = "text_labels"
    out["public_information"] = {"reagent_labels": {"source": "test", "items": [
        {"entity_id": entity_id, "label": names} for entity_id, names in sorted(labels.items())]}}
    return out


class Twin:
    """One scene, two ledgers: readback and inferred."""

    def __init__(self, labels=LABELS):
        self.scene, self.labels = Bench(), labels
        for row in self.scene.rows.values():
            if row["kind"] == "tip":
                row["available"] = True
        self.readback, self.inferred = Ledger(), Ledger()
        self.step = 0
        self._feed(None)

    def _feed(self, last_action):
        observation = self.scene.obs(self.step, last_action)
        self.readback.update(observation)
        self.inferred.update(labelled(observation, self.labels))

    def do(self, action, effect=None):
        self.readback.expect(action)
        self.inferred.expect(action)
        if effect is not None:
            effect(self.scene)
        self.step += 1
        self._feed(done(action))


def names(snapshot, section, entity_id):
    return {name for name, amount in snapshot[section][entity_id]["components_ul"].items() if amount > 0}


def carryover():
    twin = Twin()
    twin.do(ATTACH_P200, attach)
    twin.do(ASPIRATE_SAMPLE, lambda s: s.move_liquid("sample_source", "p200_tip", 140))
    twin.do(DISPENSE_LYSIS, lambda s: s.move_liquid("p200_tip", "lysis_tube", 140))
    twin.do(ASPIRATE_ETHANOL, lambda s: s.move_liquid("ethanol_95", "p200_tip", 100))
    return twin


def test_the_mode_is_detected_only_without_contents_and_with_labels():
    bench = Bench()
    assert not reads_no_contents(bench.obs(0))
    assert reads_no_contents(labelled(bench.obs(0)))
    stripped = labelled(bench.obs(0))
    del stripped["public_information"]
    assert not reads_no_contents(stripped)
    assert declared_labels(labelled(bench.obs(0))) == LABELS


def test_inferred_compositions_match_the_readback_through_a_carryover():
    twin = carryover()
    rb, inf = twin.readback.snapshot(), twin.inferred.snapshot()
    assert inf["composition_source"] == "inferred"
    for entity_id in ("sample_source", "lysis_tube", "ethanol_95"):
        assert names(inf, "containers", entity_id) == names(rb, "containers", entity_id)
        for name, amount in rb["containers"][entity_id]["components_ul"].items():
            assert inf["containers"][entity_id]["components_ul"][name] == pytest.approx(amount)
    assert names(inf, "tips", "p200_tip") == names(rb, "tips", "p200_tip")
    assert twin.inferred.tip_exposure("p200_tip") == twin.readback.tip_exposure("p200_tip") \
        == {"sample", "AVL", "ethanol_95"}
    assert [c.composition_before_ul.keys() for c in twin.inferred.tips["p200_tip"].contacts] == \
        [c.composition_before_ul.keys() for c in twin.readback.tips["p200_tip"].contacts]
    assert not [item for item in twin.inferred.unconfirmed if item["kind"] == "provenance_conflict"]


def test_rows_say_their_composition_is_inferred():
    snapshot = carryover().inferred.snapshot()
    row = snapshot["containers"]["lysis_tube"]
    assert row["composition_inferred"] is True and row["composition_uncertain"] is False


def test_readback_mode_snapshot_is_unchanged():
    snapshot = carryover().readback.snapshot()
    assert "composition_source" not in snapshot
    assert all("composition_inferred" not in row for section in ("containers", "tips")
               for row in snapshot[section].values())


def test_a_multi_name_label_keeps_every_name_and_is_uncertain():
    twin = Twin({**LABELS, "lysis_tube": ["AVL", "carrier_rna"]})
    snapshot = twin.inferred.snapshot()
    assert set(snapshot["containers"]["lysis_tube"]["components_ul"]) == {"AVL", "carrier_rna"}
    assert snapshot["containers"]["lysis_tube"]["composition_uncertain"] is True
    assert sum(snapshot["containers"]["lysis_tube"]["components_ul"].values()) == pytest.approx(560.)
    twin.do(ATTACH_P200, attach)
    twin.do({"action": "aspirate", "target": "lysis_tube", "volume_ul": 100},
            lambda s: s.move_liquid("lysis_tube", "p200_tip", 100))
    tip = twin.inferred.snapshot()["tips"]["p200_tip"]
    assert set(tip["components_ul"]) == {"AVL", "carrier_rna"} and tip["composition_uncertain"] is True


def test_an_unexplained_volume_change_is_a_provenance_conflict_and_keeps_names():
    twin = Twin()
    twin.scene.rows["lysis_tube"]["volume_ul"] = 900.  # something arrived; no confirmed action
    twin.scene.rows["lysis_tube"]["components_ul"]["unknown_x"] = 340.
    twin.do({"action": "wait", "duration_s": 1})
    snapshot = twin.inferred.snapshot()
    assert snapshot["containers"]["lysis_tube"]["composition_uncertain"] is True
    assert "AVL" in snapshot["containers"]["lysis_tube"]["components_ul"]
    assert sum(snapshot["containers"]["lysis_tube"]["components_ul"].values()) == pytest.approx(900.)
    kinds = [item["kind"] for item in twin.inferred.unconfirmed]
    assert "provenance_conflict" in kinds


def test_an_unlabelled_container_that_gains_liquid_unexplained_holds_unknown_contents():
    twin = Twin({k: v for k, v in LABELS.items() if k != "ethanol_95"})
    snapshot = twin.inferred.snapshot()
    assert snapshot["containers"]["ethanol_95"]["components_ul"] == {}
    assert snapshot["containers"]["ethanol_95"]["composition_uncertain"] is True
    assert any(item["kind"] == "provenance_conflict" and item.get("container") == "ethanol_95"
               for item in twin.inferred.unconfirmed)


def test_an_emptied_container_has_no_composition():
    twin = Twin()
    twin.do(ATTACH_P200, attach)
    twin.scene.rows["p200_tip"]["capacity_ul"] = 5000
    twin.do({"action": "aspirate", "target": "lysis_tube", "volume_ul": 560},
            lambda s: s.move_liquid("lysis_tube", "p200_tip", 560))
    snapshot = twin.inferred.snapshot()
    assert snapshot["containers"]["lysis_tube"]["components_ul"] == {}
    assert snapshot["tips"]["p200_tip"]["components_ul"] == pytest.approx({"AVL": 560.})


def test_check_against_does_not_report_inferred_composition_as_a_mismatch():
    twin = carryover()
    observation = labelled(twin.scene.obs(twin.step))
    assert not [p for p in twin.inferred.check_against(observation) if "components_ul" in p]

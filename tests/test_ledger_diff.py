"""The ledger diff (no platform needed)."""
from safelab.ledger import Ledger, diff, format_diff
from scene import Bench, done


def test_identical_snapshots_have_no_changes():
    snap = {"containers": {"a": {"volume_ul": 1., "components_ul": {"x": 1.}}}}
    assert diff(snap, snap) == []


def test_numbers_within_tolerance_are_equal_and_beyond_it_are_changed():
    before = {"containers": {"a": {"volume_ul": 100.}}}
    assert diff(before, {"containers": {"a": {"volume_ul": 100.0000001}}}) == []
    assert diff(before, {"containers": {"a": {"volume_ul": 99.}}}) == [
        {"path": "containers.a.volume_ul", "op": "changed", "before": 100., "after": 99.}]


def test_components_appearing_and_disappearing_are_added_and_removed():
    before = {"components_ul": {"pbs": 1000.}}
    after = {"components_ul": {"naocl": 500.}}
    assert diff(before, after) == [
        {"path": "components_ul.naocl", "op": "added", "after": 500.},
        {"path": "components_ul.pbs", "op": "removed", "before": 1000.}]


def test_an_appended_contact_is_reported_as_one_added_item():
    first = {"step": 1, "container": "a"}
    second = {"step": 2, "container": "b"}
    changes = diff({"contacts": [first]}, {"contacts": [first, second]})
    assert changes == [{"path": "contacts[1]", "op": "added", "after": second}]


def test_a_list_that_is_not_extended_is_reported_whole():
    assert diff({"loaded": ["a", "b"]}, {"loaded": ["b"]}) == [
        {"path": "loaded", "op": "changed", "before": ["a", "b"], "after": ["b"]}]


def test_actions_are_reported_as_one_change_not_field_by_field():
    before = {"last_action": {"action": {"action": "attach_tip", "pipette_type": "P200"}}}
    after = {"last_action": {"action": {"action": "aspirate", "target": "s", "volume_ul": 1}}}
    [change] = diff(before, after)
    assert change["path"] == "last_action" and change["op"] == "changed"


def test_format_diff_gives_one_line_per_change():
    text = format_diff([
        {"path": "a.v", "op": "changed", "before": 1, "after": 2},
        {"path": "a.c", "op": "added", "after": {"x": 1}},
        {"path": "a.d", "op": "removed", "before": "y"}])
    assert text.splitlines() == ['~ a.v: 1 -> 2', '+ a.c = {"x": 1}', '- a.d (was "y")']


def test_update_returns_the_diff_between_successive_snapshots():
    scene, ledger = Bench(), Ledger()
    ledger.update(scene.obs(0))
    before = ledger.snapshot()
    action = {"action": "attach_tip", "pipette_type": "P200"}
    scene.attached = "p200_tip"
    scene.rows["p200_tip"]["location"] = "pipette"
    changes = ledger.update(scene.obs(1, done(action)))
    assert changes == diff(before, ledger.snapshot())
    paths = {c["path"] for c in changes}
    assert {"robot.attached_tip", "tips.p200_tip.status", "tips.p200_tip.location",
            "last_action", "step_index"} <= paths
    assert not any(p.startswith("containers.") for p in paths)

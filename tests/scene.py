"""Hand-built observations in the platform's schema, for tests that run without it."""
from copy import deepcopy


def container(entity_id, volume, components, *, closure="open", capacity=5000.,
              location="table"):
    return {"entity_id": entity_id, "kind": "container", "volume_ul": volume,
            "capacity_ul": capacity, "components_ul": dict(components),
            "closure_status": closure, "location": location, "support": location}


def tip(entity_id, tip_type, *, held=0., components=None, location="tip_rack", capacity=200):
    return {"entity_id": entity_id, "kind": "tip", "type": tip_type, "volume_ul": held,
            "capacity_ul": capacity, "components_ul": dict(components or {}),
            "held_volume_ul": held, "location": location}


def device(entity_id, *, status="idle", active=False, loaded=None):
    row = {"entity_id": entity_id, "kind": "device", "type": "vortex", "status": status,
           "active": active}
    if loaded is not None:
        row["loaded_entities"] = list(loaded)
    return row


def observation(step, entities, *, held=None, attached=None, last_action=None):
    obs = {"observation_schema_version": 1, "source": "dry_run", "step_index": step,
           "robot": {"held_object_id": held, "tool_held": True, "attached_tip": attached},
           "entities": deepcopy(entities)}
    if last_action is not None:
        obs["last_action"] = deepcopy(last_action)
    return obs


def done(action):
    return {"action": dict(action), "status": "complete"}


def failed(action, error="refused"):
    return {"action": dict(action), "status": "failed", "error": error}


class Bench:
    """A tiny scene: sample, AVL tube, shared ethanol, one tip per type."""

    def __init__(self):
        self.rows = {
            "sample_source": container("sample_source", 1000., {"sample": 1000.}),
            "lysis_tube": container("lysis_tube", 560., {"AVL": 560.}, capacity=2000.),
            "ethanol_95": container("ethanol_95", 2000., {"ethanol_95": 2000.}),
            "p200_tip": tip("p200_tip", "P200"),
            "p1000_tip": tip("p1000_tip", "P1000", capacity=1000),
            "vortex_station": device("vortex_station"),
        }
        self.attached = None
        self.held = None

    def obs(self, step, last_action=None):
        return observation(step, list(self.rows.values()), held=self.held,
                           attached=self.attached, last_action=last_action)

    def move_liquid(self, source, target, volume):
        """Proportional transfer, the way the dry run books it."""
        src, dst = self.rows[source], self.rows[target]
        share = volume/src["volume_ul"]
        moved = {k: v*share for k, v in src["components_ul"].items()}
        src["volume_ul"] -= volume
        src["components_ul"] = {k: v-moved[k] for k, v in src["components_ul"].items()
                                if v-moved[k] > 1e-9}
        dst["volume_ul"] += volume
        for k, v in moved.items():
            dst["components_ul"][k] = dst["components_ul"].get(k, 0.)+v
        if src["kind"] == "tip":
            src["held_volume_ul"] = src["volume_ul"]
        if dst["kind"] == "tip":
            dst["held_volume_ul"] = dst["volume_ul"]

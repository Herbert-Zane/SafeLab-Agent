"""The execution ledger: SafeLab's working memory of the bench.

Two things move the ledger, and nothing else does:

* the observation the platform reads back each turn, and
* an action the platform reports in that observation as ``complete``.

What a model says it did, or intends to do, is never an input. ``expect()``
only notes the action SafeLab handed to the platform, as an item awaiting
readback; it changes no bench state.

State values (volumes, composition, closure, what is held, device status) are
copied from the readback, never computed from an action. The one thing the
readback cannot show is history, so the ledger derives it from confirmed
actions plus readback on either side of them:

* each tip's contact history -- step, action, container, and the container's
  composition just before and just after the contact;
* each tip's lifecycle -- ``fresh`` (available and never attached since the
  ledger began at step 0), ``attached`` (on any pipette), ``discarded``
  (unavailable and off every pipette), or ``unknown`` (earlier history or
  availability is missing). ``fresh_tips()`` lists the confirmed unused tips.

Where the readback disagrees with what a confirmed action should have done, or
something changed that no confirmed action explains, the ledger does not
correct anything: it records an item under ``unconfirmed``.

``actions`` is the platform's own report of every action it carried out or
refused, in order (``last_action`` of each observation), so it is readback too.

One field is SafeLab's own state rather than the bench's: ``stage``, the
planner's current stage. Only the planner sets it (``set_stage``); it is never
inferred from readback and no bench field depends on it. It is in the snapshot
so that every logged ledger state says which stage it was taken in.

The ledger makes no safety judgement and does not need the platform installed.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field

LIQUID_KINDS = ("container", "well")
TIP_ACTIONS = ("aspirate", "dispense")
OPENING_ACTIONS = ("open_lid", "plate_unseal")
CLOSING_ACTIONS = ("close_lid", "plate_seal")
CLOSED_STATES = ("closed", "sealed")
#: Tip lifecycle states.
TIP_STATES = ("fresh", "attached", "discarded", "unknown")
#: Kinds of item recorded under ``unconfirmed``.
ITEM_KINDS = (
    "history_gap",             # an observation was skipped, or the ledger began mid-episode
    "readback_mismatch",       # the platform carried out something other than what SafeLab returned
    "effect_not_observed",     # a confirmed action's effect is missing from the readback
    "unexplained_change",      # liquid or closure changed; no confirmed action explains it
    "contact_without_tip",     # a transfer was confirmed while the readback showed no tip
    "discarded_tip_reattached",
)

_CONTAINER_FIELDS = ("volume_ul", "capacity_ul", "components_ul", "closure_status",
                     "location", "support")
_TIP_FIELDS = ("held_volume_ul", "components_ul", "location", "available", "attached_to")
_DEVICE_FIELDS = ("status", "active", "loaded_entities", "program", "power")
_PIPETTE_FIELDS = ("type", "capacity_ul", "location", "support", "attached_tip")
_LIQUID_FIELDS = ("volume_ul", "components_ul")


@dataclass
class Container:
    kind: str
    volume_ul: float | None = None
    capacity_ul: float | None = None
    components_ul: dict = field(default_factory=dict)
    closure_status: str | None = None
    location: str | None = None
    support: str | None = None


@dataclass(frozen=True)
class Contact:
    """One confirmed aspirate or dispense: what the tip met, and when."""
    step: int
    action: str
    container: str
    composition_before_ul: dict
    composition_after_ul: dict


@dataclass
class Tip:
    tip_type: str | None = None
    capacity_ul: float | None = None
    status: str = "unknown"
    held_volume_ul: float | None = None
    components_ul: dict = field(default_factory=dict)
    location: str | None = None
    available: bool | None = None
    attached_to: str | None = None
    contacts: list = field(default_factory=list)


@dataclass
class Device:
    device_type: str | None = None
    status: str | None = None
    active: bool | None = None
    loaded_entities: list | None = None
    program: str | None = None
    power: str | None = None


class Ledger:
    """Readback-only working memory. See the module docstring for the rules."""

    def __init__(self, *, tolerance_ul=0.5, tolerance_rel=0.02):
        #: Tolerance for checking a confirmed action's effect against readback.
        #: The dry run is exact; the simulator moves real liquid.
        self.tolerance_ul = float(tolerance_ul)
        self.tolerance_rel = float(tolerance_rel)
        self.step_index = None
        self.source = None
        self.held_object = None
        self.tool_held = None
        self.held_tool = None
        self.attached_tip = None
        self.pipette_type = None
        self.containers = {}
        self.tips = {}
        self.devices = {}
        self.pipettes = {}
        self.last_action = None
        self.pending = None
        self.unconfirmed = []
        #: Every action the platform reported as carried out or refused, in order.
        self.actions = []
        #: The planner's current stage (SafeLab state, not bench state).
        self.stage = None

    # -- inputs ----------------------------------------------------------

    def expect(self, action):
        """Note the action SafeLab is returning. Changes no bench state."""
        self.pending = {"action": deepcopy(action), "returned_at_step": self.step_index}

    def set_stage(self, stage):
        """Record the planner's current stage. Changes no bench state."""
        self.stage = deepcopy(stage)

    def update(self, observation):
        """Fold one platform observation into the ledger; return the diff it caused."""
        _require_observation(observation)
        before = self.snapshot()
        step = observation["step_index"]
        first = self.step_index is None
        prior_containers = deepcopy(self.containers)
        prior_pipettes = deepcopy(self.pipettes)
        prior_tool = self.held_tool
        prior_tip = self.attached_tip
        prior_tip_held = self.tips[prior_tip].held_volume_ul if prior_tip in self.tips else None

        reported = observation.get("last_action")
        self._check_sequence(step, reported, first)
        confirmed, action_step = self._confirm(reported, step)
        self._read(observation, step, first)
        if confirmed is not None:
            self._record_contact(confirmed, action_step, prior_tip, prior_containers, step)
            self._check_effects(confirmed, action_step, prior_containers, prior_tip,
                                prior_tip_held, step)
        if not first:
            self._check_unexplained(confirmed, prior_containers, step,
                                    prior_pipettes, prior_tool)
        self.step_index = step
        self.source = observation.get("source")
        return diff(before, self.snapshot())

    # -- queries ---------------------------------------------------------

    def fresh_tips(self, tip_type=None):
        """Tips never attached since step 0, optionally of one type."""
        return sorted(tip_id for tip_id, tip in self.tips.items()
                      if tip.status == "fresh" and (tip_type is None or tip.tip_type == tip_type))

    def tip_exposure(self, tip_id):
        """Every component a tip has met in a confirmed contact, or holds now."""
        tip = self.tips[tip_id]
        met = {name for contact in tip.contacts
               for composition in (contact.composition_before_ul, contact.composition_after_ul)
               for name, amount in composition.items() if amount and amount > 0}
        met.update(name for name, amount in tip.components_ul.items() if amount and amount > 0)
        return met

    def completed_count(self, *names):
        """How many actions with one of ``names`` the platform reported complete."""
        return sum(1 for row in self.actions
                   if row["status"] == "complete" and row["action"].get("action") in names)

    def snapshot(self):
        """The whole ledger as plain, JSON-serializable data (a deep copy)."""
        return {
            "step_index": self.step_index,
            "source": self.source,
            "stage": deepcopy(self.stage),
            "robot": {"held_object": self.held_object, "tool_held": self.tool_held,
                      "held_tool": self.held_tool,
                      "attached_tip": self.attached_tip, "pipette_type": self.pipette_type},
            "containers": {cid: asdict(c) for cid, c in sorted(self.containers.items())},
            "tips": {tid: asdict(t) for tid, t in sorted(self.tips.items())},
            "devices": {did: asdict(d) for did, d in sorted(self.devices.items())},
            "pipettes": deepcopy(self.pipettes),
            "last_action": deepcopy(self.last_action),
            "pending": deepcopy(self.pending),
            "unconfirmed": deepcopy(self.unconfirmed),
            "actions": deepcopy(self.actions),
        }

    def check_against(self, observation):
        """Fields where the ledger disagrees with an observation's readback."""
        return mismatches(self.snapshot(), observation)

    # -- internals -------------------------------------------------------

    def _flag(self, kind, step, detail, **extra):
        assert kind in ITEM_KINDS, kind
        self.unconfirmed.append({"kind": kind, "step": step, "detail": detail, **extra})

    def _check_sequence(self, step, reported, first):
        if first:
            if step != 0:
                self._flag("history_gap", step,
                           f"ledger started at step {step}; earlier contacts are unknown")
            return
        status = (reported or {}).get("status")
        expected = self.step_index+1 if status in ("complete", "failed") else self.step_index
        if step != expected:
            self._flag("history_gap", step,
                       f"expected step {expected} after {status or 'no reported action'}, "
                       f"observed step {step}")

    def _confirm(self, reported, step):
        """Record the platform's report of the last action; return it if complete."""
        if not reported:
            self.last_action = None
            self.pending = None
            return None, None
        status = reported.get("status")
        action = deepcopy(reported.get("action"))
        action_step = step-1 if status in ("complete", "failed") else None
        self.last_action = {"step": action_step, "status": status, "action": action,
                            "error": reported.get("error")}
        if status in ("complete", "failed") and isinstance(action, dict):
            self.actions.append(deepcopy(self.last_action))
        if self.pending is not None and action is not None and action != self.pending["action"]:
            self._flag("readback_mismatch", step,
                       "the platform reports a different action from the one SafeLab returned",
                       returned=self.pending["action"], reported=action)
        self.pending = None
        return (action, action_step) if status == "complete" and action else (None, None)

    def _read(self, observation, step, first):
        robot = observation.get("robot") or {}
        rows = {row["entity_id"]: row for row in observation["entities"]}
        self.pipettes = {eid: {name: deepcopy(row.get(name)) for name in _PIPETTE_FIELDS}
                         for eid, row in rows.items() if row.get("kind") == "pipette"}
        self.held_object = robot.get("held_object_id")
        self.tool_held = robot.get("tool_held")
        self.held_tool = _held_pipette(rows, robot)
        held = self.pipettes.get(self.held_tool) or {}
        attached = (robot.get("attached_tip") or held.get("attached_tip")) \
            if self.tool_held else None
        self.attached_tip = attached
        self.pipette_type = held.get("type")
        attached_tips = {p["attached_tip"] for p in self.pipettes.values()
                         if p.get("attached_tip") is not None}
        if attached is not None:
            attached_tips.add(attached)
        self.containers = {}
        self.devices = {}
        for entity_id, row in rows.items():
            kind = row.get("kind")
            if kind in LIQUID_KINDS:
                self.containers[entity_id] = Container(
                    kind=kind, **{name: deepcopy(row.get(name)) for name in _CONTAINER_FIELDS
                                  if name != "components_ul"},
                    components_ul=deepcopy(row.get("components_ul") or {}))
            elif kind == "tip":
                self._read_tip(entity_id, row, attached_tips, step, first)
            elif kind == "device":
                self.devices[entity_id] = Device(
                    device_type=row.get("type"),
                    **{name: deepcopy(row.get(name)) for name in _DEVICE_FIELDS})

    def _read_tip(self, tip_id, row, attached, step, first):
        tip = self.tips.get(tip_id)
        if tip is None:
            tip = Tip(status="fresh" if first and step == 0 and row.get("available") is True
                      else "unknown")
            self.tips[tip_id] = tip
        if tip_id in attached or row.get("attached_to") is not None:
            if tip.status == "discarded":
                self._flag("discarded_tip_reattached", step,
                           f"{tip_id} was discarded earlier and reads back as attached",
                           tip=tip_id)
            tip.status = "attached"
        elif row.get("available") is False or tip.status == "attached":
            tip.status = "discarded"
        elif tip.status == "fresh" and row.get("available") is not True:
            tip.status = "unknown"
        tip.tip_type = row.get("type")
        tip.capacity_ul = row.get("capacity_ul")
        tip.held_volume_ul = row.get("held_volume_ul")
        tip.components_ul = deepcopy(row.get("components_ul") or {})
        tip.location = row.get("location")
        tip.available = row.get("available")
        tip.attached_to = row.get("attached_to")

    def _record_contact(self, action, action_step, prior_tip, prior_containers, step):
        if action.get("action") not in TIP_ACTIONS:
            return
        target = action.get("target")
        if prior_tip is None or prior_tip not in self.tips:
            self._flag("contact_without_tip", step,
                       f"{action['action']} on {target} was confirmed but no tip read back "
                       "as attached before it", action=deepcopy(action))
            return
        before = prior_containers.get(target)
        after = self.containers.get(target)
        self.tips[prior_tip].contacts.append(Contact(
            step=action_step, action=action["action"], container=target,
            composition_before_ul=deepcopy(before.components_ul) if before else {},
            composition_after_ul=deepcopy(after.components_ul) if after else {}))

    def _close(self, observed, expected):
        return abs(observed-expected) <= max(self.tolerance_ul, self.tolerance_rel*abs(expected))

    def _check_effects(self, action, action_step, prior_containers, prior_tip, prior_tip_held,
                       step):
        name, target = action.get("action"), action.get("target")
        problems = []
        if name in TIP_ACTIONS and action.get("volume_ul") is not None:
            volume = float(action["volume_ul"])
            sign = -1. if name == "aspirate" else 1.
            before, after = prior_containers.get(target), self.containers.get(target)
            if before and after and before.volume_ul is not None and after.volume_ul is not None:
                change = after.volume_ul-before.volume_ul
                if not self._close(change, sign*volume):
                    problems.append(f"{target} volume changed by {change:+g} uL; "
                                    f"the action implies {sign*volume:+g} uL")
            tip = self.tips.get(prior_tip)
            if tip and prior_tip_held is not None and tip.held_volume_ul is not None:
                change = tip.held_volume_ul-prior_tip_held
                if not self._close(change, -sign*volume):
                    problems.append(f"{prior_tip} held volume changed by {change:+g} uL; "
                                    f"the action implies {-sign*volume:+g} uL")
        elif name in OPENING_ACTIONS or name in CLOSING_ACTIONS:
            container = self.containers.get(target)
            if container is not None:
                wanted = ("open",) if name in OPENING_ACTIONS else CLOSED_STATES
                if container.closure_status not in wanted:
                    problems.append(f"{target} reads back {container.closure_status!r} "
                                    f"after {name}")
        elif name == "pick_up":
            held = self.held_tool if target in self.pipettes else self.held_object
            if held != target:
                problems.append(f"the hand holds {held!r}, not {target}")
        elif name == "put_down":
            held = self.held_tool if target in self.pipettes else self.held_object
            if held == target:
                problems.append(f"the hand still holds {target}")
            if target in self.pipettes:
                location = self.pipettes[target].get("location")
                if location != action.get("support"):
                    problems.append(f"{target} reads back at {location!r}, "
                                    f"not {action.get('support')}")
            container = self.containers.get(target)
            if container is not None and container.support != action.get("support"):
                problems.append(f"{target} reads back on {container.support!r}, "
                                f"not {action.get('support')}")
        elif name == "attach_tip":
            tip = self.tips.get(self.attached_tip) if self.attached_tip else None
            if tip is None:
                problems.append("no tip reads back as attached")
            elif self.attached_tip != action.get("tip_id"):
                problems.append(f"{self.attached_tip} reads back as attached, "
                                f"not {action.get('tip_id')}")
        elif name == "eject_tip" and self.attached_tip is not None:
            problems.append(f"{self.attached_tip} still reads back as attached")
        for problem in problems:
            self._flag("effect_not_observed", step, problem,
                       action=deepcopy(action), action_step=action_step)

    def _check_unexplained(self, confirmed, prior_containers, step, prior_pipettes, prior_tool):
        """Liquid or closure changes that no confirmed action accounts for."""
        confirmed = confirmed or {}
        name = confirmed.get("action")
        liquid_explained = set()
        if name in TIP_ACTIONS:
            liquid_explained = {confirmed.get("target")}
        elif name == "pour":
            liquid_explained = {confirmed.get("target"), confirmed.get("receiver")}
        closure_explained = ({confirmed.get("target")}
                             if name in OPENING_ACTIONS or name in CLOSING_ACTIONS else set())
        for container_id, now in self.containers.items():
            before = prior_containers.get(container_id)
            if before is None:
                continue
            changed = []
            if container_id not in liquid_explained:
                changed += [f for f in _LIQUID_FIELDS
                            if not _equal(getattr(before, f), getattr(now, f), 1e-6)]
            if (container_id not in closure_explained
                    and before.closure_status != now.closure_status):
                changed.append("closure_status")
            if changed:
                self._flag("unexplained_change", step,
                           f"{container_id} changed ({', '.join(changed)}) with no confirmed "
                           f"action to account for it",
                           container=container_id, fields=changed,
                           after_action=deepcopy(confirmed) or None)
        for pipette_id, now in self.pipettes.items():
            before = prior_pipettes.get(pipette_id)
            if before is None:
                continue
            explained = set()
            if name in ("pick_up", "put_down") and confirmed.get("target") == pipette_id:
                explained.add("location")
            if name in ("attach_tip", "eject_tip") and prior_tool == pipette_id:
                explained.add("attached_tip")
            changed = [f for f in ("location", "attached_tip")
                       if f not in explained and before.get(f) != now.get(f)]
            if changed:
                self._flag("unexplained_change", step,
                           f"{pipette_id} changed ({', '.join(changed)}) with no confirmed "
                           "action to account for it", pipette=pipette_id, fields=changed,
                           after_action=deepcopy(confirmed) or None)


# -- module helpers -------------------------------------------------------


def _held_pipette(rows, robot):
    """Text observations identify the held tool by its execution-layer location."""
    if not robot.get("tool_held"):
        return None
    held = [eid for eid, row in rows.items()
            if row.get("kind") == "pipette" and row.get("location") == "g2"]
    return held[0] if len(held) == 1 else None


def _require_observation(observation):
    if not isinstance(observation, dict):
        raise ValueError("An observation must be a dict")
    step = observation.get("step_index")
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("An observation needs a non-negative integer step_index")
    entities = observation.get("entities")
    if not isinstance(entities, list) or not all(
            isinstance(row, dict) and isinstance(row.get("entity_id"), str) for row in entities):
        raise ValueError("An observation needs an entities list of rows with entity_id")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _equal(a, b, tolerance):
    if _is_number(a) and _is_number(b):
        return math.isclose(a, b, rel_tol=0., abs_tol=tolerance)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_equal(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y, tolerance) for x, y in zip(a, b, strict=True))
    return a == b


#: Snapshot paths compared as whole values: an action is one thing, not a set of fields.
ATOMIC_PATHS = ("last_action", "pending")


def diff(before, after, *, tolerance=1e-6, atomic=ATOMIC_PATHS):
    """Changes between two ledger snapshots, as a flat list.

    Each change is ``{"path", "op", ...}`` with ``op`` one of ``added``
    (``after``), ``removed`` (``before``) or ``changed`` (both). A list whose
    old items are an unchanged prefix of the new one -- a tip's contact
    history -- reports only the appended items. Numbers within ``tolerance``
    count as equal. Paths in ``atomic`` are reported as one change.
    """
    changes = []
    _walk(before, after, "", changes, tolerance, frozenset(atomic))
    return changes


def _walk(a, b, path, out, tolerance, atomic):
    if path in atomic:
        if not _equal(a, b, tolerance):
            out.append({"path": path, "op": "changed", "before": deepcopy(a),
                        "after": deepcopy(b)})
    elif isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in a:
                out.append({"path": sub, "op": "added", "after": deepcopy(b[key])})
            elif key not in b:
                out.append({"path": sub, "op": "removed", "before": deepcopy(a[key])})
            else:
                _walk(a[key], b[key], sub, out, tolerance, atomic)
    elif (isinstance(a, list) and isinstance(b, list) and len(b) > len(a)
          and _equal(a, b[:len(a)], tolerance)):
        for index in range(len(a), len(b)):
            out.append({"path": f"{path}[{index}]", "op": "added", "after": deepcopy(b[index])})
    elif not _equal(a, b, tolerance):
        out.append({"path": path, "op": "changed", "before": deepcopy(a), "after": deepcopy(b)})


def format_diff(changes):
    """One readable line per change, for logs and the console."""
    def show(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    lines = []
    for change in changes:
        if change["op"] == "added":
            lines.append(f"+ {change['path']} = {show(change['after'])}")
        elif change["op"] == "removed":
            lines.append(f"- {change['path']} (was {show(change['before'])})")
        else:
            lines.append(f"~ {change['path']}: {show(change['before'])} -> "
                         f"{show(change['after'])}")
    return "\n".join(lines)


def mismatches(snapshot, observation, *, tolerance=1e-9):
    """Where a ledger snapshot disagrees with an observation's readback."""
    problems = []
    rows = {row["entity_id"]: row for row in observation.get("entities", [])}
    robot = observation.get("robot") or {}
    for name, key in (("held_object", "held_object_id"), ("tool_held", "tool_held"),
                      ("attached_tip", "attached_tip")):
        if snapshot["robot"].get(name) != robot.get(key):
            problems.append(f"robot.{name}: ledger {snapshot['robot'].get(name)!r}, "
                            f"readback {robot.get(key)!r}")
    held_tool = _held_pipette(rows, robot)
    for name, expected in (("held_tool", held_tool),
                           ("pipette_type", (rows.get(held_tool) or {}).get("type"))):
        if snapshot["robot"].get(name) != expected:
            problems.append(f"robot.{name}: ledger {snapshot['robot'].get(name)!r}, "
                            f"readback {expected!r}")
    observed = {eid for eid, row in rows.items() if row.get("kind") in LIQUID_KINDS}
    if observed != set(snapshot["containers"]):
        problems.append(f"container set differs: ledger {sorted(snapshot['containers'])}, "
                        f"readback {sorted(observed)}")
    groups = (("containers", LIQUID_KINDS, _CONTAINER_FIELDS),
              ("tips", ("tip",), _TIP_FIELDS),
              ("devices", ("device",), _DEVICE_FIELDS),
              ("pipettes", ("pipette",), _PIPETTE_FIELDS))
    for section, kinds, names in groups:
        for entity_id, row in rows.items():
            if row.get("kind") not in kinds:
                continue
            held = snapshot[section].get(entity_id)
            if held is None:
                problems.append(f"{section}.{entity_id} missing from the ledger")
                continue
            for name in names:
                expected = row.get(name)
                if name == "components_ul":
                    expected = expected or {}
                if not _equal(held.get(name), expected, tolerance):
                    problems.append(f"{section}.{entity_id}.{name}: ledger "
                                    f"{held.get(name)!r}, readback {expected!r}")
    return problems

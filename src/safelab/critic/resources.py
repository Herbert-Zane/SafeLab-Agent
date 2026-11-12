"""What the critic can point at and what is still available on the bench.

* ``resolve(obj, path)`` -- a ledger evidence path such as
  ``tips.p200_tip.contacts[1].composition_before_ul.AVL`` or ``action.target``,
  in the notation of ``safelab.ledger.diff``;
* ``inventory(snapshot, observation)`` -- the resources a replacement action may
  use: fresh tips by type, the attached tip and what it holds, what the hand
  holds, where a tip can be ejected;
* ``feasible(action, snapshot, observation)`` -- whether one action can be
  carried out now with those resources. It mirrors the preconditions the
  platform states in its refusals; it is a check on a replacement the critic
  proposes, not a model of the platform.

No platform import.
"""
from __future__ import annotations

import math
import re

LIQUID_KINDS = ("container", "well")
CLOSED = ("closed", "sealed")
#: Every action name the platform's vocabulary offers an agent, plus ``finish``.
# The default agent vocabulary (opt-in operations are not offered by this critic).
_PARAMETERS = {
    "attach_tip": (("tip_id",), ()),
    "eject_tip": (("target",), ()),
    "aspirate": (("target", "volume_ul"), ()),
    "dispense": (("target", "volume_ul"), ()),
    "pick_up": (("target",), ()),
    "put_down": (("target", "support"), ()),
    "pour": (("target", "receiver"), ("angle_deg", "dwell_s")),
    "open_lid": (("target",), ()),
    "close_lid": (("target",), ()),
    "plate_seal": (("target",), ()),
    "plate_unseal": (("target",), ()),
    "vortex": (("target", "duration_s"), ("device",)),
    "incubate": (("target", "duration_s", "condition"), ("device",)),
    "heat": (("target", "duration_s", "temperature_c"), ("device",)),
    "press_button": (("target",), ("control",)),
    "wait": (("target", "duration_s"), ("simulation_duration_s",)),
    "instrument_load": (("target", "device"), ()),
    "instrument_start": (("device", "program", "duration_s"), ("simulation_duration_s",)),
    "instrument_stop": (("device",), ()),
    "instrument_unload": (("target", "device"), ()),
    "finish": ((), ("reason",)),
}
ACTION_NAMES = tuple(sorted(_PARAMETERS))
_STEP = re.compile(r"\[(\d+)\]")
_MISSING = object()


def resolve(obj, path):
    """``(True, value)`` for a path that exists in ``obj``, else ``(False, None)``.

    Keys are separated by ``.`` and list items written ``[n]``. A key that itself
    contains a dot is matched whole (the longest key that fits).
    """
    if not isinstance(path, str) or not path:
        return False, None
    node, rest = obj, path
    while rest:
        if rest.startswith("["):
            match = _STEP.match(rest)
            if not match or not isinstance(node, list):
                return False, None
            index = int(match.group(1))
            if index >= len(node):
                return False, None
            node, rest = node[index], rest[match.end():]
        elif isinstance(node, list):
            match = re.match(r"(\d+)(?=$|[.\[])", rest)     # tolerate "contacts.1"
            if not match or int(match.group(1)) >= len(node):
                return False, None
            node, rest = node[int(match.group(1))], rest[match.end():]
        else:
            if not isinstance(node, dict):
                return False, None
            key = _longest_key(node, rest)
            if key is None:
                return False, None
            node, rest = node[key], rest[len(key):]
        if rest.startswith("."):
            rest = rest[1:]
            if not rest:
                return False, None
    return True, node


def _longest_key(node, rest):
    best = None
    for key in node:
        text = str(key)
        if rest.startswith(text) and (len(rest) == len(text) or rest[len(text)] in ".["):
            if best is None or len(text) > len(str(best)):
                best = key
    return best


def same_value(a, b, tolerance=1e-6):
    """Equality for cited evidence: numbers within ``tolerance``, containers recursively."""
    a, b = _numeric(a), _numeric(b)
    if _number(a) and _number(b):
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=tolerance)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(map(str, a)) == set(map(str, b)) and all(
            same_value(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_value(x, y, tolerance)
                                        for x, y in zip(a, b, strict=True))
    return a == b


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric(value):
    """A number written as a string ("800" or "800.0") counts as that number."""
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return number if math.isfinite(number) else value
    return value


def positive(components):
    return {name: amount for name, amount in (components or {}).items()
            if _number(amount) and amount > 1e-9}


def kinds(observation):
    """Entity id -> kind, from the observation (empty without one)."""
    return {row.get("entity_id"): row.get("kind")
            for row in (observation or {}).get("entities") or [] if isinstance(row, dict)}


def entity_ids(snapshot, observation):
    return ({*(snapshot.get("containers") or {}), *(snapshot.get("tips") or {}),
             *(snapshot.get("devices") or {}), *(snapshot.get("pipettes") or {})}
            | set(kinds(observation)))


def attached(snapshot):
    tip_id = (snapshot.get("robot") or {}).get("attached_tip")
    return tip_id, (snapshot.get("tips") or {}).get(tip_id) if tip_id else None


def fresh_tips(snapshot):
    return sorted((tip_id, tip.get("tip_type")) for tip_id, tip in
                  (snapshot.get("tips") or {}).items() if tip.get("status") == "fresh"
                  and tip.get("available") is True and tip.get("attached_to") is None)


def held_source(snapshot):
    """The container the attached tip's liquid came from (its last aspirate), or None."""
    _, tip = attached(snapshot)
    if tip is None or (tip.get("held_volume_ul") or 0) <= 1e-6:
        return None
    for contact in reversed(tip.get("contacts") or []):
        if contact.get("action") == "aspirate":
            return contact.get("container")
    return None


def last_tip_type(snapshot):
    """The type of the attached tip, else of the tip attached most recently, else None."""
    tips = snapshot.get("tips") or {}
    _, tip = attached(snapshot)
    if tip is not None:
        return tip.get("tip_type")
    for row in reversed(snapshot.get("actions") or []):
        action = row.get("action") or {}
        if row.get("status") == "complete" and action.get("action") == "attach_tip":
            used = tips.get(action.get("tip_id")) or {}
            return used.get("tip_type")
    return None


def observed_docks(snapshot):
    """Docks known from public parked locations or confirmed docking actions.

    A held pipette reads back at ``g2``; its earlier parked location must be
    retained by the caller, rather than guessed from an entity's name.
    """
    docks = {}
    pipettes = snapshot.get("pipettes") or {}
    for row in snapshot.get("actions") or []:
        action = row.get("action") or {}
        if (row.get("status") == "complete" and action.get("action") == "put_down"
                and action.get("target") in pipettes):
            docks[action["target"]] = action.get("support")
    for entity, row in pipettes.items():
        location = row.get("location")
        if location and location not in ("g2", "held"):
            docks[entity] = location
    return docks


def eject_target(snapshot, observation):
    """Where a used tip goes: where earlier tips went, else a waste region or tip remover."""
    for row in reversed(snapshot.get("actions") or []):
        action = row.get("action") or {}
        if row.get("status") == "complete" and action.get("action") == "eject_tip":
            return action.get("target")
    known = kinds(observation)
    for candidate in ("waste", "tip_remover", "tip_waste"):
        if candidate in known:
            return candidate
    return next((entity for entity, kind in known.items() if kind == "region"), None)


def inventory(snapshot, observation):
    """The resources a replacement action may use, as plain data."""
    tip_id, tip = attached(snapshot)
    held = None
    if tip is not None:
        held = {"tip": tip_id, "tip_type": tip.get("tip_type"),
                "held_volume_ul": tip.get("held_volume_ul"),
                "holds": positive(tip.get("components_ul")),
                "touched": sorted({c.get("container") for c in tip.get("contacts") or []})}
    discarded = sorted(t for t, row in (snapshot.get("tips") or {}).items()
                       if row.get("status") == "discarded")
    robot = snapshot.get("robot") or {}
    return {"attached_tip": held,
            "fresh_tips": [{"tip": t, "tip_type": kind} for t, kind in fresh_tips(snapshot)],
            "discarded_tips": discarded,
            "hand_holds": robot.get("held_object") or robot.get("held_tool"),
            "held_tool": robot.get("held_tool"), "pipette_type": robot.get("pipette_type"),
            "pipettes": {pid: {key: row.get(key) for key in
                               ("type", "location", "attached_tip")}
                         for pid, row in (snapshot.get("pipettes") or {}).items()},
            "eject_target": eject_target(snapshot, observation)}


def describe_inventory(inv):
    """One line for a reason text."""
    fresh = ", ".join(f"{row['tip']} ({row['tip_type']})" for row in inv["fresh_tips"]) or "none"
    if inv["attached_tip"]:
        tip = inv["attached_tip"]
        state = (f"{tip['tip']} ({tip['tip_type']}) attached, holding "
                 f"{tip['held_volume_ul'] or 0:g} uL")
    else:
        state = "no tip attached to the held pipette" if inv["held_tool"] else "no pipette held"
    tool = inv["held_tool"]
    hand = (f"hand holds {tool} ({inv['pipette_type']})" if tool
            else f"hand holds {inv['hand_holds'] or 'nothing'}")
    pipettes = ", ".join(f"{pid} ({row['type']}) at {row['location']}; "
                         f"attached tip {row['attached_tip'] or 'none'}"
                         for pid, row in sorted(inv["pipettes"].items())) or "none observed"
    return (f"Resources now: {hand}; {state}; pipettes: {pipettes}; "
            f"tips never attached: {fresh}.")


def feasible(action, snapshot, observation, *, docks=None):
    """Problems that would stop ``action`` now (empty list: feasible)."""
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        return ["not an action object"]
    name = action["action"]
    if name not in ACTION_NAMES:
        return [f"unknown action {name!r}"]
    required, optional = _PARAMETERS[name]
    missing = [key for key in required if action.get(key) is None]
    if missing:
        return [f"{name} needs a {', '.join(missing)}"]
    unexpected = set(action) - {"action", *required, *optional}
    if unexpected:
        return [f"{name} does not take {', '.join(sorted(unexpected))}"]
    containers = snapshot.get("containers") or {}
    devices = snapshot.get("devices") or {}
    pipettes = snapshot.get("pipettes") or {}
    known = entity_ids(snapshot, observation)
    robot = snapshot.get("robot") or {}
    tool = robot.get("held_tool")
    hand = robot.get("held_object") or tool
    tip_id, tip = attached(snapshot)
    problems = []
    for key in ("target", "support", "device", "receiver", "tip_id"):
        if key in action and (not isinstance(action[key], str) or action[key] not in known):
            problems.append(f"{key}={action[key]!r} is not on the bench")
    for key in ("volume_ul", "duration_s", "simulation_duration_s", "temperature_c",
                "angle_deg", "dwell_s"):
        if key in action and (not _number(action[key]) or not math.isfinite(action[key])
                              or action[key] <= 0):
            problems.append(f"{key} must be a finite positive number")
    for key in ("condition", "program", "control", "reason"):
        if key in action and (not isinstance(action[key], str) or not action[key].strip()):
            problems.append(f"{key} must be a nonempty string")
    if problems:
        return problems
    if name == "finish":
        return []
    target = action.get("target")
    volume = action.get("volume_ul")
    rows = {row.get("entity_id"): row for row in (observation or {}).get("entities") or []}
    for section in (containers, devices, pipettes, snapshot.get("tips") or {}):
        rows.update(section)
    if name in ("attach_tip", "eject_tip", "aspirate", "dispense"):
        if tool not in pipettes:
            return [f"{name} requires a pipette held in the hand"]
    if name == "attach_tip":
        if tip_id is not None:
            return [f"{tip_id} is still attached to {tool}"]
        wanted = pipettes[tool].get("type")
        if not wanted:
            return [f"the type of held pipette {tool} is unknown"]
        requested = action["tip_id"]
        row = (snapshot.get("tips") or {}).get(requested)
        if row is None:
            return [f"{requested} is not a tip the ledger tracks"]
        status = row.get("status")
        if status == "discarded":
            return [f"{requested} was used and ejected; a discarded tip cannot be attached again"]
        if status != "fresh" or row.get("available") is not True \
                or row.get("attached_to") is not None:
            return [f"{requested} is not a fresh available tip (status {status!r})"]
        if row.get("tip_type") != wanted:
            return [f"{requested} is a {row.get('tip_type') or 'untyped'} tip and does "
                    f"not fit a {wanted} pipette ({tool})"]
        return []
    if name == "eject_tip":
        if tip is None:
            return ["no tip is attached"]
        if (tip.get("held_volume_ul") or 0) > 1e-6:
            return [f"{tip_id} still holds liquid"]
        return []
    if name in ("aspirate", "dispense"):
        if tip is None:
            return ["no tip is attached"]
        container = containers.get(target)
        if container is None:
            return [f"{target} is not a liquid container"]
        if container.get("closure_status") not in (None, "open"):
            problems.append(f"{target} is {container.get('closure_status')}")
        held = tip.get("held_volume_ul") or 0
        if name == "aspirate":
            if held > 1e-6:
                problems.append(f"{tip_id} already holds liquid")
            current = container.get("volume_ul") or 0
            if volume > current+1e-6:
                problems.append(f"{target} holds only {current:g} uL")
            capacity = pipettes[tool].get("capacity_ul")
            if not _number(capacity):
                problems.append(f"the capacity of held pipette {tool} is unknown")
            elif volume > capacity+1e-6:
                problems.append(f"{tool} holds at most {capacity:g} uL")
        else:
            if volume > held+1e-6:
                problems.append(f"{tip_id} holds {held:g} uL")
            capacity, current = container.get("capacity_ul"), container.get("volume_ul") or 0
            if _number(capacity) and current+volume > capacity+1e-6:
                problems.append(f"{target} would exceed its capacity")
        return problems
    if name in ("close_lid", "plate_seal", "open_lid", "plate_unseal"):
        container = rows.get(target)
        if container is None:
            return [f"{target} has no closure the ledger tracks"]
        wanted = "open" if name in ("close_lid", "plate_seal") else "closed"
        status = container.get("closure_status")
        if status != wanted:
            problems.append(f"{target} is {status!r}")
        if hand is not None:
            problems.append(f"the hand holds {hand}")
        return problems
    if name in ("pick_up", "press_button") and hand is not None:
        return [f"the hand holds {hand}"]
    if name == "put_down":
        if (tool if target in pipettes else robot.get("held_object")) != target:
            return [f"the hand does not hold {target}"]
        if target in pipettes:
            if tip_id is not None or pipettes[target].get("attached_tip") is not None:
                return [f"{target} still has a tip attached"]
            dock = {**(docks or {}), **observed_docks(snapshot)}.get(target)
            if dock is None:
                return [f"the dock of {target} has not been observed"]
            if action["support"] != dock:
                return [f"{target} can only be put down at its dock {dock}"]
    if name == "press_button" and target not in devices:
        return [f"{target} is not a device"]
    if name == "press_button" and devices[target].get("power") is None:
        # Only a device that reads a power switch back has a control to press.
        return [f"{target} has no pressable control"]
    if name in ("vortex", "incubate", "heat"):
        wanted = {"vortex": ("vortex", "vortex_mixer"),
                  "incubate": ("incubation_environment",), "heat": ("heating_bath",)}[name]
        device_id = action.get("device")
        if device_id is None:
            matches = [did for did, row in devices.items() if row.get("device_type") in wanted]
            if len(matches) != 1:
                return [f"cannot identify a unique {wanted[0]} device"]
            device_id = matches[0]
        device = devices.get(device_id) or {}
        if name == "incubate" and hand is not None:
            return [f"incubation requires an unoccupied hand; it holds {hand}"]
        if name == "vortex":
            if tool is not None:
                return [f"vortex requires a hand free of tools; it holds {tool}"]
            # The dry run exposes a power readback for bench-top vortex mixers.
            mixer = device.get("device_type") == "vortex_mixer" or device.get("power") is not None
            if mixer:
                if robot.get("held_object") != target:
                    problems.append(f"vortexing on {device_id} requires {target} held in the hand")
                if not device.get("active"):
                    problems.append(f"{device_id} is not running")
            elif hand is not None or rows[target].get("support") != device_id:
                problems.append(f"vortexing on {device_id} requires {target} resting on it "
                                "and an empty hand")
    if name in ("instrument_start", "instrument_stop", "instrument_load", "instrument_unload"):
        device_id = action["device"]
        device = devices.get(device_id)
        if device is None:
            return [f"{device_id!r} is not a device"]
        if name in ("instrument_load", "instrument_unload") and device.get("active"):
            problems.append(f"{device_id} is running")
        if name == "instrument_load" and (rows[target].get("support") != device_id
                                         or robot.get("held_object") == target):
            problems.append(f"{target} is not resting in {device_id}")
        if name == "instrument_unload" and target not in (device.get("loaded_entities") or []):
            problems.append(f"{target} is not loaded in {device_id}")
        if name == "instrument_start" and not device.get("loaded_entities"):
            problems.append(f"{device_id} has nothing loaded")
    if name == "pour":
        return ["the dry run does not model pour"]
    return problems

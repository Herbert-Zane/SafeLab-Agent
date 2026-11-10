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
ACTION_NAMES = ("aspirate", "attach_tip", "close_lid", "dispense", "eject_tip", "incubate",
                "instrument_load", "instrument_start", "instrument_stop", "instrument_unload",
                "move", "open_lid", "pick_up", "plate_seal", "plate_unseal", "pour",
                "press_button", "put_down", "vortex", "wait", "finish")
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
             *(snapshot.get("devices") or {})} | set(kinds(observation)))


def attached(snapshot):
    tip_id = (snapshot.get("robot") or {}).get("attached_tip")
    return tip_id, (snapshot.get("tips") or {}).get(tip_id) if tip_id else None


def fresh_tips(snapshot):
    return sorted((tip_id, tip.get("tip_type")) for tip_id, tip in
                  (snapshot.get("tips") or {}).items() if tip.get("status") == "fresh")


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
            return used.get("tip_type") or action.get("pipette_type")
    return None


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
    return {"attached_tip": held,
            "fresh_tips": [{"tip": t, "tip_type": kind} for t, kind in fresh_tips(snapshot)],
            "discarded_tips": discarded,
            "hand_holds": (snapshot.get("robot") or {}).get("held_object"),
            "eject_target": eject_target(snapshot, observation)}


def describe_inventory(inv):
    """One line for a reason text."""
    fresh = ", ".join(f"{row['tip']} ({row['tip_type']})" for row in inv["fresh_tips"]) or "none"
    if inv["attached_tip"]:
        tip = inv["attached_tip"]
        state = (f"{tip['tip']} ({tip['tip_type']}) attached, holding "
                 f"{tip['held_volume_ul'] or 0:g} uL")
    else:
        state = "no tip attached"
    return f"Resources now: {state}; tips never attached: {fresh}."


def feasible(action, snapshot, observation):
    """Problems that would stop ``action`` now (empty list: feasible)."""
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        return ["not an action object"]
    name = action["action"]
    if name not in ACTION_NAMES:
        return [f"unknown action {name!r}"]
    if name == "finish":
        return []
    containers = snapshot.get("containers") or {}
    devices = snapshot.get("devices") or {}
    known = entity_ids(snapshot, observation)
    hand = (snapshot.get("robot") or {}).get("held_object")
    tip_id, tip = attached(snapshot)
    problems = []
    for key in ("target", "support", "device", "receiver", "tip_id"):
        if key in action and action[key] not in known:
            problems.append(f"{key}={action[key]!r} is not on the bench")
    if problems:
        return problems
    target = action.get("target")
    volume = action.get("volume_ul")
    if name == "attach_tip":
        if tip_id is not None:
            return [f"{tip_id} is still attached; eject it first"]
        wanted = str(action.get("pipette_type") or "").upper()
        if not wanted:
            return ["attach_tip needs a pipette_type"]
        requested = action.get("tip_id")
        if requested:
            row = (snapshot.get("tips") or {}).get(requested)
            if row is None:
                return [f"{requested} is not a tip the ledger tracks"]
            status = row.get("status")
            if status == "discarded":
                return [f"{requested} was used and ejected; a discarded tip cannot be "
                        f"attached again"]
            if status != "fresh":
                return [f"{requested} is not a fresh tip (status {status!r})"]
            if str(row.get("tip_type") or "").upper() != wanted:
                return [f"{requested} is a {row.get('tip_type') or 'untyped'} tip and does "
                        f"not fit a {wanted} pipette"]
            return []
        fresh = fresh_tips(snapshot)
        if not any(str(kind or "").upper() == wanted for _, kind in fresh):
            return [f"no fresh {wanted} tip remains (fresh: "
                    f"{', '.join(t for t, _ in fresh) or 'none'})"]
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
        if not _number(volume) or volume <= 0:
            return problems+["volume_ul must be a positive number"]
        held = tip.get("held_volume_ul") or 0
        if name == "aspirate":
            if held > 1e-6:
                problems.append(f"{tip_id} already holds liquid")
            if _number(container.get("volume_ul")) and volume > container["volume_ul"]+1e-6:
                problems.append(f"{target} holds only {container['volume_ul']:g} uL")
            if _number(tip.get("capacity_ul")) and volume > tip["capacity_ul"]+1e-6:
                problems.append(f"{tip_id} holds at most {tip['capacity_ul']:g} uL")
        else:
            if volume > held+1e-6:
                problems.append(f"{tip_id} holds {held:g} uL")
            capacity, current = container.get("capacity_ul"), container.get("volume_ul")
            if _number(capacity) and _number(current) and current+volume > capacity+1e-6:
                problems.append(f"{target} would exceed its capacity")
        return problems
    if name in ("close_lid", "plate_seal", "open_lid", "plate_unseal"):
        container = containers.get(target)
        if container is None:
            return [f"{target} has no closure the ledger tracks"]
        wanted = "open" if name in ("close_lid", "plate_seal") else CLOSED
        status = container.get("closure_status")
        if (status != wanted) if isinstance(wanted, str) else (status not in wanted):
            problems.append(f"{target} is {status!r}")
        if hand is not None:
            problems.append(f"the hand holds {hand}")
        return problems
    if name in ("pick_up", "press_button") and hand is not None:
        return [f"the hand holds {hand}"]
    if name == "put_down" and hand != target:
        return [f"the hand does not hold {target}"]
    if name in ("instrument_start", "instrument_stop", "instrument_load", "instrument_unload"):
        if action.get("device") not in devices:
            return [f"{action.get('device')!r} is not a device"]
    if name == "pour" and target not in containers:
        return [f"{target} is not a liquid container"]
    return problems

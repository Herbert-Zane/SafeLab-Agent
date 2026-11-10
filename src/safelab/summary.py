"""Plain-text views of the ledger for the planner and the actor.

Everything rendered here is a fact the platform read back or confirmed:
volumes, composition, closure, location, which tip is attached, which
containers each tip has entered and what they held at the time. Nothing here
judges a state, ranks an option or warns about anything. A line such as
``contacts: step 1 aspirate sample_source (held sample)`` says where a tip has
been; what to make of it is the model's decision.

No platform import.
"""
from __future__ import annotations

import json
import re

LEDGER_SECTIONS = ("containers", "tips", "devices")


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{value:g}" if abs(value-round(value)) > 1e-9 else str(int(round(value)))


def _composition(components):
    parts = [f"{name} {_num(amount)} uL" for name, amount in sorted((components or {}).items())
             if amount]
    return ", ".join(parts) if parts else "empty"


def _names(components):
    names = sorted(name for name, amount in (components or {}).items() if amount)
    return ", ".join(names) if names else "nothing"


def container_line(entity_id, row):
    parts = [f"{entity_id} ({row.get('kind', 'container')}): {_num(row.get('volume_ul'))} uL"]
    if row.get("capacity_ul") is not None:
        parts[0] += f" of {_num(row['capacity_ul'])} uL capacity"
    parts.append(_composition(row.get("components_ul")))
    if row.get("closure_status"):
        parts.append(row["closure_status"])
    if row.get("location"):
        parts.append(f"at {row['location']}")
    return "; ".join(parts)


def tip_line(entity_id, row, *, contacts=True):
    head = f"{entity_id} (tip {row.get('tip_type') or '?'}): {row.get('status', 'unknown')}"
    parts = [head]
    if row.get("held_volume_ul"):
        held = _composition(row.get("components_ul"))
        parts.append(f"holds {_num(row['held_volume_ul'])} uL ({held})")
    if row.get("location"):
        parts.append(f"at {row['location']}")
    if contacts:
        rows = row.get("contacts") or []
        if rows:
            listed = ", ".join(f"step {c['step']} {c['action']} {c['container']} "
                               f"(held {_names(c.get('composition_before_ul'))})" for c in rows)
            parts.append(f"contacts: {listed}")
        else:
            parts.append("contacts: none recorded")
    return "; ".join(parts)


def device_line(entity_id, row):
    parts = [f"{entity_id} (device {row.get('device_type') or '?'}): {row.get('status') or '?'}"]
    if row.get("active") is not None:
        parts.append("active" if row["active"] else "inactive")
    if row.get("program"):
        parts.append(f"program {row['program']}")
    if row.get("loaded_entities") is not None:
        parts.append(f"loaded: {', '.join(row['loaded_entities']) or 'nothing'}")
    return "; ".join(parts)


def robot_line(snapshot):
    robot = snapshot.get("robot") or {}
    held = robot.get("held_object") or "nothing"
    tip = robot.get("attached_tip") or "none"
    pipette = f"; pipette {robot['pipette_type']}" if robot.get("pipette_type") else ""
    return f"robot: holding {held}; attached tip {tip}{pipette}"


def _other_rows(observation, skip):
    """Observed rows the ledger does not model (lids, supports, pipette), if they say anything."""
    lines = []
    for row in (observation or {}).get("entities", []):
        entity_id = row.get("entity_id")
        if entity_id in skip or row.get("kind") in ("container", "well", "tip", "device"):
            continue
        detail = [f"{k} {row[k]}" for k in ("type", "location", "support", "attached_tip")
                  if row.get(k) not in (None, "")]
        if detail:
            lines.append(f"{entity_id} ({row.get('kind')}): {', '.join(detail)}")
    return lines


def mentioned_ids(text, known):
    """Entity ids that occur as whole words in ``text``."""
    words = set(re.findall(r"[A-Za-z0-9_]+", text or ""))
    return {entity_id for entity_id in known if entity_id in words}


def render_ledger(snapshot, observation=None, *, focus=None):
    """The ledger as text. With ``focus``, those entities in full and the rest in brief."""
    containers = snapshot.get("containers") or {}
    tips = snapshot.get("tips") or {}
    devices = snapshot.get("devices") or {}
    robot = snapshot.get("robot") or {}
    attached = robot.get("attached_tip")
    if focus is None:
        focus = set(containers) | set(tips) | set(devices)
    focus = set(focus) | ({attached} if attached else set())
    if robot.get("held_object"):
        focus.add(robot["held_object"])
    if attached in tips:
        focus.update(c["container"] for c in tips[attached].get("contacts") or [])

    lines = [robot_line(snapshot)]
    for entity_id in sorted(focus & set(containers)):
        lines.append(container_line(entity_id, containers[entity_id]))
    for entity_id in sorted(focus & set(tips)):
        lines.append(tip_line(entity_id, tips[entity_id]))
    for entity_id in sorted(focus & set(devices)):
        lines.append(device_line(entity_id, devices[entity_id]))
    fresh = sorted(tid for tid, tip in tips.items() if tip.get("status") == "fresh")
    lines.append("tips never attached in this run: "
                 + (", ".join(f"{tid} ({tips[tid].get('tip_type')})" for tid in fresh)
                    if fresh else "none"))

    others = []
    for entity_id in sorted(set(containers)-focus):
        others.append(container_line(entity_id, containers[entity_id]))
    for entity_id in sorted(set(tips)-focus):
        others.append(tip_line(entity_id, tips[entity_id], contacts=False))
    for entity_id in sorted(set(devices)-focus):
        others.append(device_line(entity_id, devices[entity_id]))
    others += _other_rows(observation, focus)
    out = ["  "+line for line in lines]
    if others:
        out.append("Other entities:")
        out += ["  "+line for line in others]
    unconfirmed = snapshot.get("unconfirmed") or []
    if unconfirmed:
        out.append("Readback items not confirmed by an action:")
        out += [f"  step {item.get('step')}: {item.get('detail')}" for item in unconfirmed[-5:]]
    return "\n".join(out)


def render_recent(actions, k=6):
    """The last ``k`` actions the platform carried out or refused."""
    if not actions:
        return "No actions have been carried out yet."
    rows = actions[-k:]
    lines = []
    for row in rows:
        line = (f"  {row.get('step')}: {json.dumps(row.get('action'), ensure_ascii=False)} "
                f"-> {row.get('status')}")
        if row.get("error"):
            line += f" ({row['error']})"
        lines.append(line)
    head = f"Recent steps (last {len(rows)} of {len(actions)}):"
    return "\n".join([head, *lines])

"""Shared helpers for the offline critic evaluation set.

Everything here reads the platform only through its public pieces: the task
file's plan and scene entities (never ``criteria`` / ``goals`` / ``science`` /
``limitations``), ``expand_steps``, and ``DryRunEnvironment``. Labels come from
construction rules and from ``docs/sources.md``, never from evaluator state.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
sys.path.insert(0, str(REPO/"src"))

from safelab import bench  # noqa: E402
from safelab.ledger import Ledger  # noqa: E402

#: Task-file keys the dry run needs. Everything else (criteria, goals, ...) is dropped on load.
SCENE_KEYS = ("task", "entities", "tools", "devices", "controller", "parameters", "target_sets")

#: reference task -> fault task files (relative to configs/tasks) built from it.
FAULTS = {
    "cell_lysis": ["faults/cell_lysis_tip_reuse_fault", "faults/cell_lysis_stage_b_skip_fault"],
    "waste_segregation": ["faults/waste_segregation_mix_fault"],
    "viral_inactivation_chemical": ["faults/viral_inactivation_chemical_tip_reuse_fault"],
    "plate_washing": ["faults/plate_washing_tip_reuse"],
    "liquid_pour": ["faults/liquid_knockover"],
}


#: Directory holding the task files (and ``faults/``); None means the platform's configs/tasks.
#: eval/build_heldout.py points it at runs/variants/tasks.
TASK_DIR = None


def bench_root():
    return bench.ensure_importable()


def task_dir():
    root = bench_root()  # also puts the platform on sys.path for expand_steps
    return Path(TASK_DIR) if TASK_DIR else root/"configs"/"tasks"


def load_scene(name):
    """A task's scene and plan only. ``name`` is relative to configs/tasks, without .json."""
    path = task_dir()/f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: deepcopy(raw[key]) for key in SCENE_KEYS if key in raw}


def reference_names():
    """Reference tasks: every top-level task file; the faults/ directory is excluded."""
    return sorted(p.stem for p in task_dir().glob("*.json"))


def plan_of(scene):
    from sim.controllers.sequence import expand_steps
    return [{k: v for k, v in step.items() if k != "step_path"}
            for step in expand_steps(scene)]


class Rollout:
    """A dry-run episode driven action by action, with a ledger fed only by observations.

    ``state()`` is the (observation, snapshot) the critic would see before the next
    action; asking twice at the same step returns the same pair. ``fork()`` copies the
    whole episode so a mutated continuation can start from any step.
    """

    def __init__(self, scene):
        from agent_interface.environments.base import ActionRejected
        from agent_interface.environments.dry_run import DryRunEnvironment
        self._rejected = ActionRejected
        self.env = DryRunEnvironment(deepcopy(scene))
        self.ledger = Ledger()
        self.step = 0
        self.last_action = None
        self.error = None
        self._state = None
        self.resolved = None

    def state(self):
        if self._state is None:
            observation = self.env.observe(step_index=self.step, last_action=self.last_action)
            self.ledger.update(observation)
            self._state = (deepcopy(observation), self.ledger.snapshot())
        return deepcopy(self._state)

    def resolve(self, action):
        """Replace read-at-run-time volumes (``read_volume_ul``, ``held_volume_ul``) by numbers."""
        volume = action.get("volume_ul")
        if not isinstance(volume, dict):
            return deepcopy(action)
        snapshot = self.state()[1]
        if volume.get("held_volume_ul"):
            tip = snapshot["robot"]["attached_tip"]
            number = snapshot["tips"][tip]["held_volume_ul"] if tip else 0.
        elif "read_volume_ul" in volume:
            number = snapshot["containers"][volume["read_volume_ul"]]["volume_ul"]
        else:
            raise ValueError(f"unsupported volume spec {volume}")
        return {**action, "volume_ul": number}

    def do(self, action):
        """Execute one action. False if the dry run refuses it (the step still counts).

        The action actually executed (volumes resolved) is left in ``self.resolved``.
        """
        action = self.resolve(action)
        self.resolved = deepcopy(action)
        self.state()
        self._state = None
        try:
            self.env.execute(deepcopy(action), step_index=self.step)
        except self._rejected as exc:
            self.error = str(exc)
            self.last_action = {"action": deepcopy(action), "status": "failed", "error": str(exc)}
            self.step += 1
            return False
        self.error = None
        self.last_action = {"action": deepcopy(action), "status": "complete"}
        self.step += 1
        return True

    def advance(self, actions):
        """Execute ``actions`` in order; False at the first refusal."""
        return all(self.do(action) for action in actions)

    def fork(self):
        return deepcopy(self)


def state_after(scene, actions):
    """(observation, snapshot) after executing ``actions`` from the start; None if refused."""
    roll = Rollout(scene)
    return roll.state() if roll.advance(actions) else None


def comps(snapshot, container):
    row = snapshot["containers"].get(container)
    return {k: v for k, v in (row or {}).get("components_ul", {}).items() if v and v > 0}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(dumps(row)+"\n")


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

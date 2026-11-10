"""Argument handling shared by ``scripts/run_dry.py`` and ``scripts/run_sim.py``.

Both scripts register provider ``"safelab"`` and then hand control to a
platform entry point unchanged. This module only resolves the paths they pass
on, refuses a config that does not run the condition it was asked for, and
tells the backend (through two environment variables) where the run directory
is and which brief the run uses: the trace goes to the run directory, and the
brief decides the run's train/test split for the reflection library.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .reflexion import BRIEF_ENV
from .trace import RUN_DIR_ENV

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO/"configs"/"agents"
RUNS_DIR = REPO/"runs"


class LaunchError(ValueError):
    pass


def common_parser(description):
    # allow_abbrev=False: an option meant for the platform entry point must not
    # be swallowed as an abbreviation of one of ours.
    parser = argparse.ArgumentParser(description=description, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--condition", default="B",
                        help="Experimental condition (default B)")
    parser.add_argument("--agent", type=Path,
                        help="SafeLab agent config (default safelab_<condition>.json)")
    parser.add_argument("--config", type=Path, required=True,
                        help="Task config; tried as given, then under the platform root")
    parser.add_argument("--output", type=Path,
                        help="Run directory (default runs/<kind>/<condition>_<task>_<time>)")
    return parser


def resolve_file(path, bench_root, what="Task config"):
    """An existing file: as given, else relative to the platform root."""
    path = Path(path)
    for candidate in (path, Path(bench_root)/path):
        if candidate.is_file():
            return candidate.resolve()
    raise LaunchError(f"{what} not found: {path} (also tried under {bench_root})")


def resolve_agent(condition, agent=None):
    path = Path(agent) if agent else CONFIG_DIR/f"safelab_{condition}.json"
    if not path.is_file() and not path.is_absolute() and (REPO/path).is_file():
        path = REPO/path
    if not path.is_file():
        raise LaunchError(f"Agent config not found: {path}")
    backend = json.loads(path.read_text(encoding="utf-8")).get("backend") or {}
    if backend.get("provider") != "safelab":
        raise LaunchError(f"{path.name} does not use provider 'safelab'")
    if backend.get("condition", "B") != condition:
        raise LaunchError(f"{path.name} runs condition {backend.get('condition', 'B')!r}, "
                          f"not {condition!r}")
    return path.resolve()


def default_output(kind, condition, task_path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return (RUNS_DIR/kind/f"{condition}_{Path(task_path).stem}_{stamp}").resolve()


def brief_label(brief):
    """A brief's name as the split table knows it: the file name without ``.json``."""
    if brief is None:
        return None
    name = Path(brief).name
    return name[:-len(".json")] if name.endswith(".json") else name


def export_run_context(output, brief=None):
    """Tell the backend, created later in this process, its run directory and brief."""
    os.environ[RUN_DIR_ENV] = str(Path(output))
    label = brief_label(brief)
    if label:
        os.environ[BRIEF_ENV] = label
    else:
        os.environ.pop(BRIEF_ENV, None)
    return label

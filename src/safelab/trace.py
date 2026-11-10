"""SafeLab's event log, ``safelab_trace.jsonl``, written next to the platform's artifacts.

The platform records one row per model call. This log records what happened
inside that call, one JSON object per line, in order:

* per step: ``proposed`` (the actor's candidate), ``reviewed`` (the critic's
  verdict; condition C only, one per candidate, with ``disagreement`` when the
  rule and LLM channels disagree, and ``refusal_limit`` when the same action
  has been refused often enough in the run to end it), ``returned`` (what went
  back to the platform),
  then on the next call ``executed`` (the platform's report of that action) and
  ``observed`` (what the readback changed in the ledger);
* ``plan``, ``replan`` and ``stage`` from the planner;
* ``reflect`` (a failure classified and the strategy chosen),
  ``empty_reply``, ``reflection_read`` and ``reflection_write``;
* ``usage`` per sub-call, ``call_error``, ``retry``, ``fault`` and
  ``budget_stop`` from the resilience layer;
* ``run_start`` and ``run_end``.

Every row carries ``seq`` (0, 1, 2, ...), ``t`` (UTC time), ``event``, and the
platform ``call`` and observation ``step`` it belongs to. The file is rewritten
from empty when a backend is created, so a reused run directory never mixes two
runs. Without a run directory the log is kept in memory only (tests).

No platform import: this module is plain bookkeeping.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

FILENAME = "safelab_trace.jsonl"
#: Set by ``scripts/run_dry.py`` and ``scripts/run_sim.py`` to the platform's run directory.
RUN_DIR_ENV = "SAFELAB_RUN_DIR"

EVENTS = (
    "run_start", "run_end",
    "observed", "executed", "proposed", "reviewed", "disagreement", "refusal_limit",
    "returned",
    "plan", "replan", "stage",
    "reflect", "empty_reply", "reflection_read", "reflection_write",
    "usage", "call_error", "retry", "fault", "budget_stop",
)


def _now():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class TraceLog:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.events = []
        self.context = {"call": None, "step": None}
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    @classmethod
    def for_run(cls, run_dir=None):
        """The log for a platform run directory (default: ``$SAFELAB_RUN_DIR``, else memory)."""
        run_dir = run_dir or os.environ.get(RUN_DIR_ENV)
        return cls(Path(run_dir)/FILENAME if run_dir else None)

    def bind(self, **context):
        self.context.update(context)

    def emit(self, event, **fields):
        if event not in EVENTS:
            raise ValueError(f"Unknown trace event {event!r}")
        row = {"seq": len(self.events), "t": _now(), "event": event, **self.context, **fields}
        line = json.dumps(row, ensure_ascii=False, default=str)
        self.events.append(json.loads(line))
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line+"\n")
        return row

    def of(self, event):
        return [row for row in self.events if row["event"] == event]


def read(path):
    """The rows of a trace file."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def chain_gaps(rows):
    """Steps whose ``returned`` action lacks a later ``executed`` and ``observed`` row.

    An action handed to the platform is followed, on the next call, by the
    platform's report of it and by the readback. The last returned action of a
    run is exempt when it is ``finish`` or when no later call exists.
    """
    gaps = []
    returned = [row for row in rows if row["event"] == "returned"]
    for index, row in enumerate(returned):
        action = row.get("action") or {}
        if action.get("action") == "finish" or row.get("action") is None:
            continue
        later = [r for r in rows if r["seq"] > row["seq"] and r.get("call") == row["call"]+1]
        if not later and index == len(returned)-1:
            continue
        kinds = {r["event"] for r in later}
        missing = [k for k in ("executed", "observed") if k not in kinds]
        if missing:
            gaps.append({"call": row["call"], "step": row.get("step"), "missing": missing})
    return gaps

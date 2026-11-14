"""Exploratory batches: experiments/run_matrix.py restricted to some open-ended cells.

    CELLS=B_cl:10,C_cl:10,C_ws:5 python <path>/run_cells.py <run_matrix.py arguments>

Keeps the order and names of the pre-registered schedule and drops every slot
that is not in a listed cell or whose index is above that cell's n. Nothing in
experiments/ or src/ is changed; run_matrix.py marks the batch "formal": false.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/"experiments"))
import run_matrix as m  # noqa: E402

want = {}
for item in os.environ["CELLS"].split(","):
    cell, _, n = item.partition(":")
    want[cell] = int(n)
full = m.build_schedule


def build(n_open, n_proc):
    return [s for s in full(n_open, n_proc) if s["group"] == "open"
            and s["index"] <= want.get(f"{s['condition']}_{s['task']}", 0)]


m.build_schedule = build
sys.exit(m.main())

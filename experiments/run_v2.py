"""Runner of the confirmatory batch of preregistration_v2.md (A', A'', C on open waste).

    SAFELAB_BENCH_ROOT=<platform at e81c19e> python experiments/run_v2.py --mode sim --jobs 2
    python experiments/run_v2.py --mode sim --plan          # print the 120 slots and stop

It is experiments/run_matrix.py with the prereg-v2 design patched in; the
launch, timeout, logging, interruption and replacement logic is run_matrix.py's
own. What differs:

- cells: Ap_ws, App_ws, C_ws, 40 runs each, in 40 blocks of 3, order within a
  block shuffled with seed 20261117; output runs/confirm_v2/open/<name>;
- versions checked for "formal": SafeLab src/ and configs/ equal to tag
  prereg-v2, platform at e81c19e, agent configs and the two briefs at the
  hashes written in preregistration_v2.md;
- a backend_error whose detail says 402 / Insufficient Balance means the slot
  was not executed: its directory is moved to _not_executed/, no further slot is
  started, and the same command later re-runs that slot under the same name
  without using one of its two replacements (prereg-v1 revision 5, made a rule).
"""
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_matrix as m  # noqa: E402

SEED = 20261117
N = 40
CONDITIONS = ("Ap", "App", "C")
BRIEF_STEM = "waste_segregation_v1"
NOT_EXECUTED = re.compile(r"\b402\b|insufficient.?balance", re.I)

m.SEED = SEED
m.SAFELAB_TAG = "prereg-v2"
m.PLATFORM_COMMIT = "e81c19e"
m.GROUPS = {"open": (CONDITIONS, N), "proc": ((), 0)}
m.AGENTS = {"Ap": "configs/agents/deepseek_flash.json",
            "App": "configs/agents/deepseek_flash.json",
            "C": "configs/agents/safelab_C_flash.json"}
m.PINNED = {"configs/agents/deepseek_flash.json": "0a6917139e4c",
            "configs/agents/safelab_C_flash.json": "b897973c3ced",
            f"{BRIEF_STEM}.open.json": "11388fb24c6a",
            f"{BRIEF_STEM}.open.primed.json": "4496097e60aa",
            f"{BRIEF_STEM}.open.cards.json": "0a6050c16c0c"}


def build_schedule(n_open, n_proc=0):
    rng = __import__("random").Random(SEED)
    slots = []
    for block in range(1, n_open+1):
        cells = list(CONDITIONS)
        rng.shuffle(cells)
        for condition in cells:
            slots.append({"group": "open", "condition": condition, "task": "ws",
                          "index": block, "block": block, "position": len(slots)+1,
                          "name": f"{condition}_ws_{block:02d}"})
    return slots


def brief_for(slot, bench):
    if slot["condition"] == "Ap":
        return m.REPO/"experiments"/"briefs"/f"{BRIEF_STEM}.open.primed.json"
    if slot["condition"] == "App":
        return m.REPO/"experiments"/"briefs"/f"{BRIEF_STEM}.open.cards.json"
    return bench/"configs"/"agent_briefs"/f"{BRIEF_STEM}.open.json"


_classify = m.classify


def classify(slot, run_dir, exit_code, killed):
    run = m.read_json(run_dir/"agent_run.json") or {}
    if (not killed and run.get("outcome") == "backend_error"
            and NOT_EXECUTED.search(json.dumps(run.get("outcome_detail")))):
        return "not_executed", "backend_error: 402 insufficient balance", "backend_error", None
    return _classify(slot, run_dir, exit_code, killed)


HALT = threading.Event()
_execute, _next_attempt = m.Batch.execute, m.Batch.next_attempt


def execute(self, slot, replacement):
    _execute(self, slot, replacement)
    run_dir = self.run_dir(slot, replacement)
    meta = m.read_json(run_dir/"run_meta.json") or {}
    if meta.get("disposition") == "not_executed":
        aside = self.root/"_not_executed"/f"{run_dir.name}_{time.strftime('%Y%m%d-%H%M%S')}"
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(run_dir), str(aside))
        log = run_dir.with_name(run_dir.name+".log")
        if log.exists():
            shutil.move(str(log), str(aside)+".log")
        HALT.set()
        print(f"{run_dir.name}: not executed (402); no further slot is started", flush=True)


def next_attempt(self, slot):
    return None if HALT.is_set() else _next_attempt(self, slot)


m.build_schedule, m.brief_for, m.classify = build_schedule, brief_for, classify
m.Batch.execute, m.Batch.next_attempt = execute, next_attempt

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--out" not in argv:
        argv += ["--out", str(m.REPO/"runs"/"confirm_v2")]
    if "--group" not in argv:
        argv += ["--group", "open"]
    sys.exit(m.main(argv))

"""Runner of the v3 batches (任务分解_创新冲刺.md): observation mode x condition, one table of cells.

    SAFELAB_BENCH_ROOT=<platform with text_labels> python experiments/run_v3.py --batch pilot_v3 --mode sim --jobs 2
    python experiments/run_v3.py --batch pilot_v3 --mode sim --plan       # print the slots and stop

It is experiments/run_matrix.py with the v3 design patched in, the way run_v2.py patches it;
launch, timeout, logging, interruption, replacement and the 402 rule are the same. A cell is
(condition code, task); a condition code fixes the agent config (which carries the observation
mode), the brief and whether SafeLab runs it:

| code   | agent                         | observation | brief   | SafeLab |
|--------|-------------------------------|-------------|---------|---------|
| A      | deepseek_flash                | text_state  | neutral | no      |
| App    | deepseek_flash                | text_state  | cards   | no      |
| L      | safelab_B_flash               | text_state  | cards   | B       |
| C      | safelab_C_flash               | text_state  | neutral | C       |
| Alab   | deepseek_flash_labels         | text_labels | neutral | no      |
| Applab | deepseek_flash_labels         | text_labels | cards   | no      |
| Blab   | safelab_B_flash_labels        | text_labels | neutral | B       |
| Llab   | safelab_B_flash_labels        | text_labels | cards   | B       |
| Clab   | safelab_C_flash_labels        | text_labels | neutral | C       |
| App4   | deepseek_v4_pro               | text_state  | cards   | no      |
| C4     | safelab_C_v4pro               | text_state  | neutral | C       |

"cards" is the A'' brief: the 25 card texts in ``operating_notes`` (experiments/briefs/
<stem>.open.cards.json, made by make_brief_cards.py); "neutral" is the platform's open brief.
L is B (planner + ledger + recovery, no critic) given the same cards as A''.

Batches marked exploratory are never formal (``--allow-informal`` is added for them); a
pre-registered batch is formal only with SafeLab src/ and configs/ at its tag, the platform at
its commit, and every agent config and brief at the hash its pre-registration fixes.
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

NOT_EXECUTED = re.compile(r"\b402\b|insufficient.?balance", re.I)

#: code -> (agent config, brief kind, SafeLab condition or None)
CELLS = {
    "A": ("configs/agents/deepseek_flash.json", "neutral", None),
    "App": ("configs/agents/deepseek_flash.json", "cards", None),
    "L": ("configs/agents/safelab_B_flash.json", "cards", "B"),
    "C": ("configs/agents/safelab_C_flash.json", "neutral", "C"),
    "Alab": ("configs/agents/deepseek_flash_labels.json", "neutral", None),
    "Applab": ("configs/agents/deepseek_flash_labels.json", "cards", None),
    "Blab": ("configs/agents/safelab_B_flash_labels.json", "neutral", "B"),
    "Llab": ("configs/agents/safelab_B_flash_labels.json", "cards", "B"),
    "Clab": ("configs/agents/safelab_C_flash_labels.json", "neutral", "C"),
    "App4": ("configs/agents/deepseek_v4_pro.json", "cards", None),
    "C4": ("configs/agents/safelab_C_v4pro.json", "neutral", "C"),
}

#: Tasks beyond run_matrix.TASKS are added by the task scan (experiments/task_scan_v3/split.md).
TASKS = dict(m.TASKS)

#: batch -> design. ``pins`` None = exploratory (current hashes recorded, never formal).
#: ``grid`` lists the (condition code, task) cells; every cell gets ``n`` runs.
BATCHES = {
    "pilot_v3": {"grid": (("Alab", "ws"), ("Applab", "ws"), ("Llab", "ws"), ("Clab", "ws"), ("L", "ws"),
                          ("Alab", "cl"), ("Applab", "cl"), ("Clab", "cl")),
                 "n": 5, "seed": 20261124, "pins": None, "tag": None, "platform": None},
    "multi_model_v3": {"grid": (("App4", "ws"), ("C4", "ws")), "n": 20,
                       "seed": 20261129, "pins": None, "tag": None, "platform": None},
    # experiments/preregistration_v3.md (tag prereg-v3): fixed before the first run.
    "confirm_v3": {"grid": (("Applab", "ws"), ("Blab", "ws"), ("Llab", "ws"), ("Clab", "ws")), "n": 40,
                   "seed": 20261125, "tag": "prereg-v3", "platform": "b41eb9b",
                   "pins": {"configs/agents/deepseek_flash_labels.json": "6397b8e74e21",
                            "configs/agents/safelab_B_flash_labels.json": "521391fe886e",
                            "configs/agents/safelab_C_flash_labels.json": "07351d179923",
                            "waste_segregation_v1.open.cards.json": "0a6050c16c0c",
                            "waste_segregation_v1.open.json": "11388fb24c6a"}},
}


def brief_path(code, task, bench):
    stem = TASKS[task][1]
    kind = CELLS[code][1]
    if kind == "cards":
        return m.REPO/"experiments"/"briefs"/f"{stem}.open.cards.json"
    return bench/"configs"/"agent_briefs"/f"{stem}.open.json"


def configure(name, bench):
    """Patch run_matrix for one batch; return the design."""
    design = BATCHES[name]
    grid = design["grid"]
    codes = tuple(dict.fromkeys(code for code, _ in grid))
    m.SEED = design["seed"]
    m.TASKS = {task: TASKS[task] for task in dict.fromkeys(task for _, task in grid)}
    m.GROUPS = {"open": (codes, design["n"]), "proc": ((), 0)}
    m.AGENTS = {code: CELLS[code][0] for code in codes}
    GRID[:] = list(grid)
    if design["pins"] is None:
        files = {CELLS[code][0]: m.REPO/CELLS[code][0] for code in codes}
        files.update({brief_path(code, task, bench).name: brief_path(code, task, bench)
                      for code, task in grid})
        m.PINNED = {key: m.sha(path)[:12] for key, path in files.items()}
    else:
        m.PINNED = dict(design["pins"])
    m.SAFELAB_TAG = design["tag"] or "HEAD"
    m.PLATFORM_COMMIT = design["platform"] or ""
    return design


GRID = []


def build_schedule(n_open, n_proc=0):
    """Blocks of every grid cell, order within a block shuffled with the batch seed."""
    rng = __import__("random").Random(m.SEED)
    cells = list(GRID)
    slots = []
    for block in range(1, n_open+1):
        order = list(cells)
        rng.shuffle(order)
        for code, task in order:
            slots.append({"group": "open", "condition": code, "task": task, "index": block,
                          "block": block, "position": len(slots)+1,
                          "name": f"{code}_{task}_{block:02d}"})
    return slots


def brief_for(slot, bench):
    return brief_path(slot["condition"], slot["task"], bench)


def command(slot, mode, agent, bench, out):
    task = TASKS[slot["task"]][0]
    brief = brief_for(slot, bench)
    safelab = CELLS[slot["condition"]][2]
    brief_flag = "--agent-brief" if mode == "sim" else "--brief"
    if safelab:
        script = m.REPO/"scripts"/("run_sim.py" if mode == "sim" else "run_dry.py")
        argv = [sys.executable, str(script), "--condition", safelab,
                "--agent", str(agent), "--config", task, brief_flag, str(brief)]
        cwd = m.REPO
    else:
        argv = [sys.executable, "main.py" if mode == "sim" else "run_agent.py",
                "--config", task, "--agent", str(agent), brief_flag, str(brief)]
        cwd = bench
    if mode == "sim":
        argv.append("--headless")
    return [*argv, "--output", str(out)], cwd, brief


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


def is_safelab(slot):
    return CELLS[slot["condition"]][2] is not None


def run(self, slots):
    """run_matrix.Batch.run with SafeLab told apart by the cell table, not by the code "B"/"C".

    The reflection library is archived before every SafeLab run (memory isolation: no run
    reads another's experience); v3 has only the open group, so no run writes it."""
    pending = list(slots)
    active = {}
    while pending or active:
        for thread in [t for t in active if not t.is_alive()]:
            slot = active.pop(thread)
            if self.next_attempt(slot) is not None:
                pending.insert(0, slot)
        started = False
        if len(active) < self.args.jobs:
            for slot in pending:
                replacement = self.next_attempt(slot)
                pending.remove(slot)
                if replacement is None:
                    started = True
                    break
                if is_safelab(slot):
                    self.archive_library(slot["name"])
                thread = threading.Thread(target=self.execute, args=(slot, replacement))
                thread.start()
                active[thread] = slot
                started = True
                break
        if not started:
            time.sleep(1.0)


def main(argv):
    import os
    argv = list(argv)
    if "--batch" not in argv:
        raise SystemExit(f"--batch is required: one of {', '.join(BATCHES)}")
    index = argv.index("--batch")
    name = argv[index+1]
    del argv[index:index+2]
    if name not in BATCHES:
        raise SystemExit(f"unknown batch {name!r}; one of {', '.join(BATCHES)}")
    bench = Path(os.environ.get("SAFELAB_BENCH_ROOT", "")).resolve()
    design = configure(name, bench)
    m.build_schedule, m.brief_for, m.classify, m.command = build_schedule, brief_for, classify, command
    m.Batch.execute, m.Batch.next_attempt, m.Batch.run = execute, next_attempt, run
    if "--out" not in argv:
        argv += ["--out", str(m.REPO/"runs"/name)]
    if "--group" not in argv:
        argv += ["--group", "open"]
    if design["pins"] is None and "--allow-informal" not in argv:
        argv.append("--allow-informal")
        print(f"{name}: exploratory batch, NOT formal", flush=True)
    return m.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

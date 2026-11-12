r"""Run the pre-registered matrix (experiments/preregistration.md), resumably.

    <isaac python> experiments/run_matrix.py --mode sim --jobs 3
    .venv/Scripts/python.exe experiments/run_matrix.py --mode dry --n-open 1 --n-proc 1 \
        --agents A=<plan_replay.json>,B=configs/agents/safelab_B_scripted.json

What it fixes, following the pre-registration:

* Order. Blocks of one run per cell, shuffled inside each block with seed
  20261125; the open-ended group first, then the procedural group.
* One run = one child process (the platform's ``main.py`` for A and A', and
  ``scripts/run_sim.py`` for B and C), killed after ``--cap-s`` (3 h).
* Reflection library. It is moved away before every B or C run, and a
  procedural B or C run (which may write it when it ends) never overlaps
  another B or C run. Each B or C run is then checked to have read 0 entries.
* Exclusion. Decided from the process exit, ``agent_run.json`` and the
  ``reflection_read`` event only; evaluator output is never opened here.
  Excluded runs are kept and replaced, at most twice per slot.
* Provenance. ``run_meta.json`` in every run directory: both commits, config
  and brief hashes, times, exit code, disposition.

A run is "formal" only in sim mode, with the pre-registered configs, n and cap,
and with both checkouts passing the version checks. Anything else is recorded
with ``"formal": false``. State lives on disk, so rerunning the same command
continues where it stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEED = 20261125
PLATFORM_COMMIT = "d8bcbf9"
SAFELAB_TAG = "prereg-v1"
CAP_S = 10800
MAX_REPLACEMENTS = 2
LIBRARY = REPO/"runs"/"reflections"/"library.jsonl"

TASKS = {"ws": ("configs/tasks/waste_segregation.json", "waste_segregation_v1"),
         "cl": ("configs/tasks/cell_lysis.json", "cell_lysis_normal_execution_v1")}
#: group -> (conditions, pre-registered n per cell)
GROUPS = {"open": (("A", "Ap", "B", "C"), 10), "proc": (("A", "B", "C"), 5)}
AGENTS = {"A": "configs/agents/deepseek_flash.json", "Ap": "configs/agents/deepseek_flash.json",
          "B": "configs/agents/safelab_B_flash.json", "C": "configs/agents/safelab_C_flash.json"}
#: sha256 (first 12 hex digits, line endings normalised to LF) fixed by the pre-registration
PINNED = {"configs/agents/deepseek_flash.json": "0a6917139e4c",
          "configs/agents/safelab_B_flash.json": "709854967d39",
          "configs/agents/safelab_C_flash.json": "b897973c3ced",
          "waste_segregation_v1.open.json": "11388fb24c6a",
          "cell_lysis_normal_execution_v1.open.json": "0d8efb9f72ba",
          "waste_segregation_v1.json": "f58f188e3970",
          "cell_lysis_normal_execution_v1.json": "a5263dad446e",
          "waste_segregation_v1.open.primed.json": "4496097e60aa",
          "cell_lysis_normal_execution_v1.open.primed.json": "b62e149028e8"}
#: a backend_error is infrastructure only when its detail says the API was unreachable
UNREACHABLE = re.compile(r"connect|timed? ?out|unreachable|temporar|rate.?limit|overloaded"
                         r"|\b(429|500|502|503|504)\b|APIConnection|APITimeout", re.I)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git(root, *args):
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return done.returncode, done.stdout.strip()


def build_schedule(n_open, n_proc):
    rng = random.Random(SEED)
    slots = []
    for group, n in (("open", n_open), ("proc", n_proc)):
        conditions = GROUPS[group][0]
        for block in range(1, n+1):
            cells = [(c, t) for c in conditions for t in TASKS]
            rng.shuffle(cells)
            for condition, task in cells:
                slots.append({"group": group, "condition": condition, "task": task,
                              "index": block, "block": block, "position": len(slots)+1,
                              "name": f"{condition}_{task}_{block:02d}"})
    return slots


def brief_for(slot, bench):
    stem = TASKS[slot["task"]][1]
    if slot["group"] == "proc":
        return bench/"configs"/"agent_briefs"/f"{stem}.json"
    if slot["condition"] == "Ap":
        return REPO/"experiments"/"briefs"/f"{stem}.open.primed.json"
    return bench/"configs"/"agent_briefs"/f"{stem}.open.json"


def command(slot, mode, agent, bench, out):
    task = TASKS[slot["task"]][0]
    brief = brief_for(slot, bench)
    safelab = slot["condition"] in ("B", "C")
    brief_flag = "--agent-brief" if mode == "sim" else "--brief"
    if safelab:
        script = REPO/"scripts"/("run_sim.py" if mode == "sim" else "run_dry.py")
        argv = [sys.executable, str(script), "--condition", slot["condition"],
                "--agent", str(agent), "--config", task, brief_flag, str(brief)]
        cwd = REPO
    else:
        argv = [sys.executable, "main.py" if mode == "sim" else "run_agent.py",
                "--config", task, "--agent", str(agent), brief_flag, str(brief)]
        cwd = bench
    if mode == "sim":
        argv.append("--headless")
    return [*argv, "--output", str(out)], cwd, brief


def preflight(bench, agents, formal_shape):
    """Version checks. Returns (facts, problems); any problem makes the batch non-formal."""
    problems = []
    _, safelab_commit = git(REPO, "rev-parse", "HEAD")
    code, _ = git(REPO, "diff", "--quiet", SAFELAB_TAG, "--", "src", "configs")
    if code:
        problems.append(f"src/ or configs/ differ from {SAFELAB_TAG}")
    if git(REPO, "status", "--porcelain", "--", "src", "configs")[1]:
        problems.append("uncommitted changes under src/ or configs/")
    _, platform_commit = git(bench, "rev-parse", "HEAD")
    if not platform_commit.startswith(PLATFORM_COMMIT):
        problems.append(f"platform is at {platform_commit[:7] or 'unknown'}, not {PLATFORM_COMMIT}")
    if git(bench, "status", "--porcelain", "--untracked-files=no")[1]:
        problems.append("platform checkout has uncommitted changes")
    for condition, path in agents.items():
        relative = AGENTS[condition]
        if Path(path).resolve() != (REPO/relative).resolve():
            problems.append(f"condition {condition} uses {path}, not {relative}")
        elif not sha(path).startswith(PINNED[relative]):
            problems.append(f"{relative} does not match its pre-registered hash")
    problems.extend(formal_shape)
    return {"safelab_commit": safelab_commit, "platform_commit": platform_commit}, problems


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reflection_count(run_dir):
    """Entries the run read from the library; None when the event is missing."""
    try:
        with open(run_dir/"safelab_trace.jsonl", encoding="utf-8") as lines:
            for line in lines:
                row = json.loads(line)
                if row.get("event") == "reflection_read":
                    return row.get("count")
    except (OSError, ValueError):
        pass
    return None


def classify(slot, run_dir, exit_code, killed):
    """(disposition, reason, outcome, reflection count). Never opens evaluator output."""
    run = read_json(run_dir/"agent_run.json") or {}
    outcome = run.get("outcome")
    count = reflection_count(run_dir) if slot["condition"] in ("B", "C") else None
    if killed:
        return "counted", None, outcome, count
    if outcome is None:
        return "excluded", f"no agent_run.json (exit code {exit_code})", None, count
    if outcome == "environment_error":
        return "excluded", "environment_error", outcome, count
    if outcome == "backend_error" and UNREACHABLE.search(json.dumps(run.get("outcome_detail"))):
        return "excluded", "backend_error: API unreachable", outcome, count
    if slot["condition"] in ("B", "C") and count != 0:
        return "excluded", f"reflection_read count is {count}", outcome, count
    return "counted", None, outcome, count


def stop(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True)
    except OSError:
        process.kill()


class Batch:
    def __init__(self, args, bench, agents, facts, formal):
        self.args, self.bench, self.agents = args, bench, agents
        self.facts, self.formal = facts, formal
        self.root = args.out.resolve()

    def run_dir(self, slot, replacement):
        suffix = f"_r{replacement}" if replacement else ""
        return self.root/slot["group"]/f"{slot['name']}{suffix}"

    def next_attempt(self, slot):
        """The replacement number to run next, or None when the slot is settled."""
        for replacement in range(MAX_REPLACEMENTS+1):
            run_dir = self.run_dir(slot, replacement)
            meta = read_json(run_dir/"run_meta.json")
            if meta is None:
                marker = run_dir.with_name(run_dir.name+".started.json")
                if marker.exists() or run_dir.exists():     # the runner died mid-run
                    aside = self.root/"_interrupted"/f"{run_dir.name}_{time.strftime('%Y%m%d-%H%M%S')}"
                    aside.parent.mkdir(parents=True, exist_ok=True)
                    if run_dir.exists():
                        shutil.move(str(run_dir), str(aside))
                    marker.unlink(missing_ok=True)
                    print(f"interrupted earlier, set aside: {run_dir.name}", flush=True)
                return replacement
            if meta.get("disposition") == "counted":
                return None
        return None

    def archive_library(self, name):
        if LIBRARY.exists():
            target = self.root/"_library_archive"/f"{time.strftime('%Y%m%d-%H%M%S')}_before_{name}.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(LIBRARY), str(target))

    def execute(self, slot, replacement):
        run_dir = self.run_dir(slot, replacement)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        agent = self.agents[slot["condition"]]
        argv, cwd, brief = command(slot, self.args.mode, agent, self.bench, run_dir)
        meta = {"meta_schema": 1, "name": run_dir.name, **{k: slot[k] for k in
                ("group", "condition", "task", "index", "block", "position")},
                "replacement": replacement, "mode": self.args.mode, "formal": self.formal,
                **self.facts, "agent_config": str(agent), "agent_config_sha256": sha(agent),
                "brief": str(brief), "brief_sha256": sha(brief),
                "task_config": TASKS[slot["task"]][0], "cap_s": self.args.cap_s,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        marker = run_dir.with_name(run_dir.name+".started.json")
        marker.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        env = {**os.environ, "SAFELAB_BENCH_ROOT": str(self.bench),
               "OMNI_KIT_ACCEPT_EULA": "YES", "PYTHONIOENCODING": "utf-8"}
        killed = False
        with open(run_dir.with_name(run_dir.name+".log"), "wb") as log:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=(os.name == "posix"))
            try:
                exit_code = process.wait(timeout=self.args.cap_s)
            except subprocess.TimeoutExpired:
                killed = True
                stop(process)
                exit_code = process.wait()
        disposition, reason, outcome, count = classify(slot, run_dir, exit_code, killed)
        meta.update(ended=time.strftime("%Y-%m-%dT%H:%M:%S%z"), exit_code=exit_code,
                    killed_by_cap=killed, disposition=disposition, exclusion_reason=reason,
                    outcome=outcome, reflection_read_count=count)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir/"run_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        marker.unlink(missing_ok=True)
        print(f"{run_dir.name}: {disposition}"
              f"{' ('+reason+')' if reason else ''}, outcome {outcome}", flush=True)

    def run(self, slots):
        pending = list(slots)
        active = {}                                   # thread -> slot
        while pending or active:
            for thread in [t for t in active if not t.is_alive()]:
                slot = active.pop(thread)
                if self.next_attempt(slot) is not None:
                    pending.insert(0, slot)           # excluded: replace it next
            started = False
            if len(active) < self.args.jobs:
                safelab = [s for s in active.values() if s["condition"] in ("B", "C")]
                writer = any(s["group"] == "proc" for s in safelab)
                for slot in pending:
                    if slot["condition"] in ("B", "C"):
                        if writer or (slot["group"] == "proc" and safelab):
                            continue                  # keep the library untouched for this run
                    replacement = self.next_attempt(slot)
                    pending.remove(slot)
                    if replacement is None:
                        started = True
                        break
                    if slot["condition"] in ("B", "C"):
                        self.archive_library(slot["name"])
                    thread = threading.Thread(target=self.execute, args=(slot, replacement))
                    thread.start()
                    active[thread] = slot
                    started = True
                    break
            if not started:
                time.sleep(1.0)


def parse_agents(text):
    agents = {c: REPO/p for c, p in AGENTS.items()}
    for item in filter(None, (text or "").split(",")):
        condition, _, path = item.partition("=")
        if condition not in AGENTS or not path:
            raise SystemExit(f"--agents: expected <A|Ap|B|C>=<path>, got {item!r}")
        agents[condition] = Path(path) if Path(path).is_absolute() else REPO/path
        if condition == "A" and "Ap=" not in text:
            agents["Ap"] = agents["A"]
    return agents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("sim", "dry"), required=True)
    parser.add_argument("--out", type=Path, help="default runs/formal (sim) or runs/formal_dry")
    parser.add_argument("--jobs", type=int, default=1, help="runs in parallel, at most 5")
    parser.add_argument("--group", choices=("open", "proc", "all"), default="all")
    parser.add_argument("--n-open", type=int, default=GROUPS["open"][1])
    parser.add_argument("--n-proc", type=int, default=GROUPS["proc"][1])
    parser.add_argument("--cap-s", type=int, default=CAP_S)
    parser.add_argument("--agents", help="development only: A=path,B=path,C=path")
    parser.add_argument("--limit", type=int, help="development only: first N slots")
    parser.add_argument("--plan", action="store_true", help="print the schedule and stop")
    parser.add_argument("--allow-informal", action="store_true",
                        help="sim mode: run although the version checks fail")
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 5:
        parser.error("--jobs must be 1 to 5")
    args.out = args.out or REPO/"runs"/("formal" if args.mode == "sim" else "formal_dry")

    bench = Path(os.environ.get("SAFELAB_BENCH_ROOT", "")).resolve()
    if not (bench/"main.py").is_file():
        raise SystemExit("SAFELAB_BENCH_ROOT does not point at the platform checkout")
    agents = parse_agents(args.agents)
    slots = build_schedule(args.n_open, args.n_proc)
    if args.group != "all":
        slots = [s for s in slots if s["group"] == args.group]
    if args.limit:
        slots = slots[:args.limit]
    if args.plan:
        for slot in slots:
            print(f"{slot['position']:3d}  {slot['group']:4s} block {slot['block']:2d}  {slot['name']}")
        return 0

    shape = []
    if args.mode != "sim":
        shape.append("not a simulator run")
    if (args.n_open, args.n_proc) != (GROUPS["open"][1], GROUPS["proc"][1]) or args.limit:
        shape.append("n per cell is not the pre-registered one")
    if args.cap_s != CAP_S:
        shape.append("cap is not the pre-registered 3 h")
    for slot in slots:
        brief = brief_for(slot, bench)
        if not sha(brief).startswith(PINNED[brief.name]):
            shape.append(f"{brief.name} does not match its pre-registered hash")
    facts, problems = preflight(bench, agents, sorted(set(shape)))
    formal = not problems
    if problems:
        print("NOT a formal batch:\n  - "+"\n  - ".join(problems), flush=True)
        if args.mode == "sim" and not args.allow_informal:
            raise SystemExit("refusing a simulator batch that is not formal "
                             "(--allow-informal for integration runs)")

    args.out.mkdir(parents=True, exist_ok=True)
    plan = {"seed": SEED, "mode": args.mode, "formal": formal, "problems": problems,
            "slots": slots}
    plan_path = args.out/"schedule.json"
    earlier = read_json(plan_path)
    if earlier and (earlier["slots"] != slots or earlier["formal"] != formal):
        raise SystemExit(f"{plan_path} holds a different schedule; use another --out")
    plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    Batch(args, bench, agents, facts, formal).run(slots)
    return 0


if __name__ == "__main__":
    sys.exit(main())

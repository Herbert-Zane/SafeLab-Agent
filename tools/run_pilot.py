"""Run the P0 pilot: the platform's baseline agent (condition A) on the open briefs.

Each run is the platform's own ``run_agent.py`` dry run, unchanged. This script
only loops over models, tasks and repetitions, skips runs that already finished,
and keeps the output layout stable so ``pilot_check.py`` can read it.

    python tools/run_pilot.py --plan            # print the matrix, call nothing
    python tools/run_pilot.py --yes             # run it (spends API money)
    python tools/run_pilot.py --yes --models dsflash --tasks ws --reps 1

Default models are the two DeepSeek configs; pass --models haiku sonnet opus
for Claude. Each config names its own key variable (api_key_env).

A dry run produces no safety verdict. Whatever pilot_check.py prints from these
runs is a development signal, not an evaluation result.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path(os.environ.get("SAFELAB_BENCH_ROOT", r"D:\科学具身仿真\Benchmark\bench"))

MODELS = {
    "haiku": ROOT/"configs/agents/claude_haiku_5_5.json",
    "sonnet": BENCH/"configs/agents/claude_sonnet_5_5.json",
    "opus": BENCH/"configs/agents/claude_opus_5_5.json",
    "dsflash": ROOT/"configs/agents/deepseek_flash.json",
    "dspro": ROOT/"configs/agents/deepseek_v4_pro.json",
}
DEFAULT_MODELS = ["dsflash", "dspro"]


def key_variable(config_path):
    """The environment variable the agent config names for its API key."""
    spec = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return spec["backend"].get("api_key_env")
TASKS = {
    "ws": (BENCH/"configs/tasks/waste_segregation.json",
           BENCH/"configs/agent_briefs/waste_segregation_v1.open.json"),
    "cl": (BENCH/"configs/tasks/cell_lysis.json",
           BENCH/"configs/agent_briefs/cell_lysis_normal_execution_v1.open.json"),
}


def finished(run_dir):
    """A run counts as done once the platform wrote its summary."""
    return (run_dir/"agent_run.json").is_file()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS, choices=list(MODELS))
    parser.add_argument("--tasks", nargs="+", default=list(TASKS), choices=list(TASKS))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT/"runs/pilot")
    parser.add_argument("--plan", action="store_true", help="Print the matrix and exit")
    parser.add_argument("--yes", action="store_true", help="Actually call the model APIs")
    args = parser.parse_args(argv)

    matrix = [(m, t, r) for m in args.models for t in args.tasks for r in range(1, args.reps+1)]
    pending = [(m, t, r) for m, t, r in matrix
               if not finished(args.output/f"A_{m}_{t}_{r:02d}")]
    print(f"bench: {BENCH}")
    print(f"{len(matrix)} runs in the matrix, {len(pending)} not yet finished")
    for m, t, r in pending:
        print(f"  A_{m}_{t}_{r:02d}")
    if args.plan or not pending:
        return 0
    if not args.yes:
        print("Nothing called. Pass --yes to run these against the live API.")
        return 1
    missing = sorted({key_variable(MODELS[m]) for m, _, _ in pending} - {None}
                     - {k for k, v in os.environ.items() if v})
    if missing:
        print(f"Not set in this shell: {', '.join(missing)}")
        return 1

    failures = 0
    for m, t, r in pending:
        task, brief = TASKS[t]
        out = args.output/f"A_{m}_{t}_{r:02d}"
        cmd = [sys.executable, "run_agent.py", "--config", str(task), "--agent", str(MODELS[m]),
               "--brief", str(brief), "--output", str(out)]
        print(f"\n== A_{m}_{t}_{r:02d}", flush=True)
        result = subprocess.run(cmd, cwd=BENCH)
        if result.returncode != 0 or not finished(out):
            failures += 1
            print(f"   run did not complete (exit {result.returncode})")
        else:
            summary = json.loads((out/"agent_run.json").read_text(encoding="utf-8"))
            print(f"   outcome={summary['outcome']} cost={summary['usage'].get('cost_usd')}")
    print(f"\ndone; {failures} run(s) did not complete")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

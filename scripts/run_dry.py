r"""Dry run of a SafeLab condition through the platform's own ``run_agent.py``.

    .venv/Scripts/python.exe scripts/run_dry.py --condition B \
        --config configs/tasks/waste_segregation.json
    .venv/Scripts/python.exe scripts/run_dry.py --condition B \
        --agent configs/agents/safelab_B_scripted.json \
        --config configs/tasks/waste_segregation.json

Registers provider "safelab", then calls the platform's dry-run entry point.
Any option this script does not know (--brief, --max-steps, --print-prompt) is
passed to ``run_agent.py`` unchanged. Artifacts go to runs/dry/ by default; SafeLab's
own event log, ``safelab_trace.jsonl``, is written into the same directory. The brief's
file name decides the run's train/test split for the reflection library.

A dry run is declared bookkeeping, not physics: it produces no safety,
integrity or goal result, and nothing it prints may be reported as one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))

from safelab import bench, launch  # noqa: E402


def main(argv=None):
    parser = launch.common_parser(__doc__)
    parser.add_argument("--brief", type=Path,
                        help="Task brief; tried as given, then under the platform root")
    args, rest = parser.parse_known_args(argv)
    root = bench.ensure_importable()
    bench.register(root)
    task = launch.resolve_file(args.config, root)
    brief = args.brief
    if brief is not None:
        rest = ["--brief", str(launch.resolve_file(brief, root, "Task brief")), *rest]
    agent = launch.resolve_agent(args.condition, args.agent)
    output = (args.output.resolve() if args.output
              else launch.default_output("dry", args.condition, task))
    launch.export_run_context(output, brief)
    import run_agent  # the platform's dry-run entry point, unchanged
    return run_agent.main(["--config", str(task), "--agent", str(agent),
                           "--output", str(output), *rest])


if __name__ == "__main__":
    sys.exit(main())

r"""Simulator run of a SafeLab condition through the platform's ``main.py --agent``.

    <isaac python> scripts/run_sim.py --condition B \
        --config configs/tasks/waste_segregation.json \
        --agent-brief configs/agent_briefs/waste_segregation_v1.open.json --headless

Run it with the same interpreter that runs ``main.py`` on the GPU server:
registration only reaches ``create_backend`` inside the same process.

Registers provider "safelab", then executes the platform's ``main.py`` as
``__main__`` with the agent config and output directory filled in. Every other
option (--headless, --agent-brief, --record, ...) is passed through unchanged.
Artifacts go to runs/sim/ by default, with ``safelab_trace.jsonl`` beside them.
Safety, integrity and goal results come from the run's own
``trajectory_evaluation.json``, not from this script.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))

from safelab import bench, launch  # noqa: E402


def main(argv=None):
    parser = launch.common_parser(__doc__)
    parser.add_argument("--agent-brief", type=Path,
                        help="Task brief; tried as given, then under the platform root")
    args, rest = parser.parse_known_args(argv)
    root = bench.ensure_importable()
    bench.register(root)
    task = launch.resolve_file(args.config, root)
    brief = args.agent_brief
    if brief is not None:
        rest = ["--agent-brief", str(launch.resolve_file(brief, root, "Task brief")), *rest]
    agent = launch.resolve_agent(args.condition, args.agent)
    output = (args.output.resolve() if args.output
              else launch.default_output("sim", args.condition, task))
    launch.export_run_context(output, brief)
    main_py = root/"main.py"
    sys.argv = [str(main_py), "--config", str(task), "--agent", str(agent),
                "--output", str(output), *rest]
    runpy.run_path(str(main_py), run_name="__main__")  # main.py exits via sys.exit
    return 0


if __name__ == "__main__":
    sys.exit(main())

r"""Robustness suite (execution plan S3.2): run the cases, then report.

    .venv/Scripts/python.exe eval/robustness/run_suite.py --list
    .venv/Scripts/python.exe eval/robustness/run_suite.py --category tool_failure --jobs 3
    .venv/Scripts/python.exe eval/robustness/run_suite.py --only ui-adversarial-ws-C
    .venv/Scripts/python.exe eval/robustness/run_suite.py --report-only \
        --report eval/reports/robustness_v1

Each case in ``cases.json`` is one dry run of a SafeLab condition through
``scripts/run_dry.py``: a task, a brief, a base agent config and optional overrides merged
into that config's ``backend`` block (this is how a case switches fault injection on). The
derived config is written to ``runs/robust/_configs/``; the run goes to
``runs/robust/<case id>_<n>``. A run whose ``agent_run.json`` exists is not repeated unless
``--force`` is given.

Model cases need the key the agent config names (``DEEPSEEK_API_KEY``) in the environment.

Dry runs only: nothing this script prints is a safety result. See ``metrics.py`` for what
each number means and ``README.md`` for the cases.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO/"src"))
sys.path.insert(0, str(HERE))

import metrics  # noqa: E402

CASES = HERE/"cases.json"
OUT = REPO/"runs"/"robust"
CATEGORIES = ("tool_failure", "unexpected_input", "name_generalisation", "demo")
CATEGORY_TITLES = {"tool_failure": "Tool failure (injected timeout, 429, garbled reply)",
                   "unexpected_input": "Unexpected input (adversarial brief, vague goal, "
                                       "missing item)",
                   "name_generalisation": "Name generalisation (neutral entity ids)",
                   "demo": "Demonstration mode (per-step latency)"}


class SuiteError(ValueError):
    pass


def merge(base, extra):
    """``extra`` over ``base``, dict by dict; anything else in ``extra`` replaces."""
    out = deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def load_cases(path=CASES):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"]
    seen = set()
    for case in cases:
        missing = [key for key in ("id", "category", "task", "brief", "condition", "agent")
                   if not case.get(key)]
        if missing:
            raise SuiteError(f"case {case.get('id')!r} lacks {missing}")
        if case["category"] not in CATEGORIES:
            raise SuiteError(f"case {case['id']}: unknown category {case['category']!r}")
        if case["id"] in seen:
            raise SuiteError(f"duplicate case id {case['id']!r}")
        seen.add(case["id"])
        case.setdefault("repeats", 1)
    return cases


def select(cases, *, only=None, category=None):
    chosen = [case for case in cases if (not only or case["id"] in only)
              and (not category or case["category"] in category)]
    unknown = sorted(set(only or ())-{case["id"] for case in cases})
    if unknown:
        raise SuiteError(f"unknown case id(s): {unknown}")
    return chosen


def build_config(case, repo=REPO):
    """The case's agent config: the base file with ``overrides`` merged into ``backend``."""
    base = json.loads((Path(repo)/case["agent"]).read_text(encoding="utf-8"))
    config = deepcopy(base)
    config["backend"] = merge(base["backend"], case.get("overrides"))
    if case.get("limits"):
        config["limits"] = merge(base.get("limits") or {}, case["limits"])
    config["id"] = f"{base.get('id', 'safelab')}--{case['id']}"
    if config["backend"].get("condition", "B") != case["condition"]:
        raise SuiteError(f"case {case['id']}: {case['agent']} runs condition "
                         f"{config['backend'].get('condition', 'B')!r}, not {case['condition']!r}")
    return config


def run_dirs(case, out=OUT):
    """Where the case's runs are. ``existing`` names earlier runs to report, never to launch."""
    if case.get("existing"):
        return [REPO/path for path in case["existing"]]
    return [Path(out)/f"{case['id']}_{n}" for n in range(1, case["repeats"]+1)]


def command(case, config_path, run_dir, repo=REPO):
    return [sys.executable, str(Path(repo)/"scripts"/"run_dry.py"),
            "--condition", case["condition"], "--agent", str(config_path),
            "--config", case["task"], "--brief", case["brief"], "--output", str(run_dir)]


def run_case(case, *, out=OUT, force=False, timeout_s=3600, runner=subprocess.run):
    """Run every repeat of one case; return ``[(run_dir, status)]``."""
    out = Path(out)
    if case.get("existing"):
        return [(run_dir, "existing run, not launched") for run_dir in run_dirs(case, out)]
    config_path = out/"_configs"/f"{case['id']}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(build_config(case), ensure_ascii=False, indent=2)+"\n",
                           encoding="utf-8", newline="\n")
    results = []
    for run_dir in run_dirs(case, out):
        if (run_dir/"agent_run.json").is_file() and not force:
            results.append((run_dir, "kept"))
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            proc = runner(command(case, config_path, run_dir), cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
            text = (proc.stdout or "")+(proc.stderr or "")
            status = f"exit {proc.returncode}"
        except subprocess.TimeoutExpired as exc:
            text, status = f"timed out after {exc.timeout} s", "timeout"
        (run_dir/"suite_stdout.txt").write_text(text, encoding="utf-8")
        results.append((run_dir, f"{status} in {time.monotonic()-started:.0f} s"))
    return results


# -- report ----------------------------------------------------------------------------------------


def collect(cases, out=OUT, *, replay=None):
    rows = []
    for case in cases:
        for run_dir in run_dirs(case, out):
            row = metrics.summarise(run_dir, replay=replay)
            row.update(case=case["id"], category=case["category"], kind=case.get("kind"),
                       expect=case.get("expect"))
            rows.append(row)
    return rows


def _cell(value):
    if value is None:
        return "-"
    return f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def markdown(rows):
    lines = ["# Robustness suite report", "",
             "Dry runs. A dry run has no consequence recognition, so nothing below is a safety "
             "result; the platform's own summary of every run says `unavailable_in_dry_run`. "
             "\"Flagged executed\" is an offline replay of SafeLab's own rules R1-R6 over the "
             "actions that were carried out, not the platform's evaluator.", ""]
    for category in CATEGORIES:
        chosen = [row for row in rows if row["category"] == category and row["present"]]
        if not chosen:
            continue
        total = metrics.aggregate(chosen)
        lines += [f"## {CATEGORY_TITLES[category]}", ""]
        if category == "tool_failure":
            lines += [f"Faults injected {total['faults_injected']}, recovered "
                      f"{total['faults_recovered']} (recovery rate "
                      f"{_cell(total['recovery_rate'])}). Runs that did not complete: "
                      f"{total['not_completed']}, of which ended in a controlled stop: "
                      f"{total['controlled_stops']}.", ""]
        lines += ["| run | cond. | ending | actions ok / refused | faults inj. / rec. | "
                  "blocked proposals | flagged executed | step latency median / max (s) | "
                  "USD list / cache-adj. |", "|---|---|---|---|---|---|---|---|---|"]
        for row in chosen:
            faults, latency, money = row["faults"], row["visible_latency"], row["cost"]
            flagged = row["flagged_executed"]
            lines.append(
                f"| {row['run']} | {_cell(row['condition'])} | {row['ending']} "
                f"({_cell(row['outcome'])}) | {_cell(row['actions_completed'])} / "
                f"{_cell(row['actions_failed'])} | {faults['injected']} / {faults['recovered']} | "
                f"{len(row['review']['blocked'])} | "
                f"{'-' if flagged is None else len(flagged)} | "
                f"{_cell(latency['median_s'])} / {_cell(latency['max_s'])} | "
                f"{_cell(money['list_usd'])} / {_cell(money['cache_adjusted_usd'])} |")
        lines.append("")
        for row in chosen:
            notes = []
            for item in row["review"]["blocked"]:
                notes.append(f"  - call {item['call']}: {item['decision']} `{item['action']}` "
                             f"({', '.join(item['rule_ids']) or item['channel']})")
            for item in row["flagged_executed"] or []:
                notes.append(f"  - executed at step {item['step']}, flagged by the rule replay: "
                             f"`{item['action']}` ({', '.join(item['rule_ids'])})")
            if row["finish_reason"]:
                notes.append(f"  - finish reason: {row['finish_reason'][:300]}")
            elif row["outcome"] != "finished_by_agent" and row["outcome_detail"]:
                notes.append(f"  - {row['outcome']}: {str(row['outcome_detail'])[:300]}")
            if notes:
                lines += [f"- **{row['run']}**", *notes]
        lines.append("")
    absent = [row["run"] for row in rows if not row["present"]]
    if absent:
        lines += ["## Not run", "", ", ".join(absent), ""]
    return "\n".join(lines)


def write_report(rows, stem):
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    by_category = {category: metrics.aggregate([row for row in rows if row["present"]
                                                and row["category"] == category])
                   for category in CATEGORIES
                   if any(row["category"] == category and row["present"] for row in rows)}
    payload = {"note": "dry runs; development signals only, not an evaluation result",
               "by_category": by_category, "runs": rows}
    stem.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=1)+"\n",
                                         encoding="utf-8", newline="\n")
    stem.with_suffix(".md").write_text(markdown(rows)+"\n", encoding="utf-8", newline="\n")
    return stem


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--only", nargs="*", help="case ids")
    parser.add_argument("--category", nargs="*", choices=CATEGORIES)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--jobs", type=int, default=1, help="cases run at the same time")
    parser.add_argument("--force", action="store_true", help="repeat runs that already exist")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--report", type=Path, help="report path without extension "
                                                    "(default <out>/report)")
    parser.add_argument("--no-replay", action="store_true", help="skip the offline rule replay")
    args = parser.parse_args(argv)
    cases = select(load_cases(args.cases), only=args.only, category=args.category)
    if args.list:
        for case in cases:
            print(f"{case['id']:<28} {case['category']:<20} {case['condition']} "
                  f"x{case['repeats']}  {case.get('expect', '')}")
        return 0
    if not args.report_only:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            done = pool.map(lambda case: run_case(case, out=args.out, force=args.force), cases)
            for case, results in zip(cases, done, strict=True):
                for run_dir, status in results:
                    print(f"{case['id']:<28} {run_dir.name:<32} {status}", flush=True)
    replay = None if args.no_replay else metrics.rule_replay()
    rows = collect(cases, args.out, replay=replay)
    stem = write_report(rows, args.report or args.out/"report")
    print(f"report: {stem.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

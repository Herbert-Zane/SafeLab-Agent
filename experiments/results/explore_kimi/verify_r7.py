"""Offline replay of R7 on the final finish of logged SafeLab runs (read-only).

usage (repo root): .venv/Scripts/python.exe -X utf8 experiments/results/explore_kimi/verify_r7.py <run_root/open> [...]

Uses only safelab_trace.jsonl (ledger snapshots and diffs), never evaluator files.
Traces written before R7 have no ``device_runs``; it is rebuilt the way the ledger
derives it: each platform-confirmed ``instrument_start`` in ``actions``, with the
device's ``loaded_entities`` from the snapshot before the one that first lists it.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from console.runstore import ledger_states  # noqa: E402
from safelab.critic.rules import RuleChannel  # noqa: E402


def rebuild_runs(states, upto):
    runs, seen, prev = [], set(), None
    for call in sorted(c for c in states if c <= upto):
        snap = states[call]
        for rec in snap.get("actions") or []:
            act = rec.get("action") or {}
            key = (rec.get("step"), json.dumps(act, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            if rec.get("status") == "complete" and act.get("action") == "instrument_start":
                dev = act.get("device")
                before = ((prev or {}).get("devices") or {}).get(dev) or {}
                after = (snap.get("devices") or {}).get(dev) or {}
                loaded = before.get("loaded_entities")
                if loaded is None:
                    loaded = after.get("loaded_entities")
                runs.append({"step": rec.get("step"), "device": dev,
                             "program": act.get("program"), "loaded": loaded})
        prev = snap
    return runs


def main(roots):
    channel = RuleChannel()
    for root in roots:
        stats = Counter()
        for run in sorted(Path(root).glob("C_*_[0-9][0-9]")):
            trace = run / "safelab_trace.jsonl"
            if not run.is_dir() or not trace.exists():
                continue
            rows = [json.loads(line) for line in trace.open(encoding="utf-8")]
            states = ledger_states(rows)
            finishes = [r for r in rows if r.get("event") == "proposed"
                        and (r.get("action") or {}).get("action") == "finish"]
            if not finishes or not states:
                stats["no_finish"] += 1
                continue
            call = finishes[-1].get("call")
            upto = max(c for c in states if c <= call)
            snap = dict(states[upto])
            if "device_runs" not in snap:
                snap["device_runs"] = rebuild_runs(states, upto)
            result = channel.check(snap, None, finishes[-1]["action"])
            stats[result.status] += 1
            if result.status != "clear":
                print(result.status, run.name, finishes[-1]["action"].get("reason", "")[:200])
                print("   device_runs:", snap["device_runs"])
        print(root, dict(stats))


if __name__ == "__main__":
    main(sys.argv[1:])

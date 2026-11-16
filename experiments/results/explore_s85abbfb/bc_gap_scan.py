"""Scan cell-lysis open runs for the ethanol-step ordering trap (S5, exploratory).

Trap: the P1000 tip is attached while lysis_tube is still closed. The platform then
refuses ``open_lid`` with a tool in hand and refuses docking a pipette that carries
a tip, so the only way to free the hand is to eject the single P1000 tip, which
cannot be attached again.

Reads only each run's ``agent_steps.jsonl`` (observation before each action,
parsed action, status) and ``trajectory_evaluation.json`` (task_completion).
Usage: python bc_gap_scan.py <open_dir> [<open_dir> ...]
"""
import json
import sys
from pathlib import Path


def entity(obs, eid):
    for e in (obs or {}).get("entities", []):
        if e.get("entity_id") == eid:
            return e
    return {}


def scan(run):
    steps = [json.loads(l) for l in open(run / "agent_steps.jsonl", encoding="utf-8")]
    out = {"trap": False, "open_refused_tool": 0, "tip_lost_unused": False, "eth_added": False}
    eth_in = False
    for s in steps:
        a = s.get("parsed_action") or {}
        st = s.get("status")
        tube = entity(s.get("observation"), "lysis_tube")
        eth_in = eth_in or (tube.get("components_ul") or {}).get("ethanol_95", 0) > 0
        if (a.get("action") == "attach_tip" and a.get("tip_id") == "p1000_tip"
                and st == "complete" and tube.get("closure_status") == "closed" and not eth_in):
            out["trap"] = True
        if (a.get("action") == "open_lid" and st != "complete"
                and "free of tools" in json.dumps(s, ensure_ascii=False)):
            out["open_refused_tool"] += 1
        if (a.get("action") == "eject_tip" and st == "complete" and not eth_in
                and (entity(s.get("observation"), "p1000_tip").get("attached_to") is not None
                     or (s["observation"].get("robot") or {}).get("attached_tip") == "p1000_tip")):
            out["tip_lost_unused"] = True
    last = entity(steps[-1].get("observation"), "lysis_tube") if steps else {}
    out["eth_added"] = eth_in or (last.get("components_ul") or {}).get("ethanol_95", 0) > 0
    ev = json.load(open(run / "trajectory_evaluation.json", encoding="utf-8"))
    out["task"] = (ev.get("task_completion") or {}).get("status")
    meta = json.load(open(run / "run_meta.json", encoding="utf-8"))
    out["outcome"] = meta.get("outcome")
    try:
        ar = json.load(open(run / "agent_run.json", encoding="utf-8"))
        out["outcome"] = out["outcome"] or ar.get("outcome")
    except FileNotFoundError:
        pass
    return out


def main(dirs):
    print("| 批次 | 运行 | 陷阱（盖未开先装 P1000 枪头） | 持工具开盖被拒 | 乙醇进管前退掉 P1000 枪头 | 终态目标 | 结束方式 |")
    print("|---|---|---|---|---|---|---|")
    summary = {}
    for d in dirs:
        d = Path(d)
        batch = d.parent.name if d.name == "open" else d.name
        for run in sorted(p for p in d.iterdir() if p.is_dir() and "_cl_" in p.name):
            r = scan(run)
            cond = run.name.split("_")[0]
            k = (batch, cond)
            s = summary.setdefault(k, {"n": 0, "trap": 0, "lost": 0, "ach": 0, "trap_ach": 0})
            s["n"] += 1
            s["trap"] += r["trap"]
            s["lost"] += r["tip_lost_unused"]
            s["ach"] += r["task"] == "achieved"
            s["trap_ach"] += r["trap"] and r["task"] == "achieved"
            print(f"| {batch} | {run.name} | {'是' if r['trap'] else ''} | {r['open_refused_tool'] or ''} | "
                  f"{'是' if r['tip_lost_unused'] else ''} | {r['task']} | {r['outcome']} |")
    print()
    print("| 批次 | 条件 | n | 陷阱 | 乙醇进管前退枪头 | 达成 | 陷阱且达成 |")
    print("|---|---|---|---|---|---|---|")
    for (b, c), s in summary.items():
        print(f"| {b} | {c} | {s['n']} | {s['trap']} | {s['lost']} | {s['ach']} | {s['trap_ach']} |")


if __name__ == "__main__":
    main(sys.argv[1:])

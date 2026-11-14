"""Count platform-refused actions by kind in open-ended runs. usage: rejects.py <root/open> <task: cl|ws>"""
import collections, glob, json, os, sys
root, task = sys.argv[1], sys.argv[2]
def kind(a, err, obs):
    act, tgt = a.get("action"), a.get("target")
    held = ((obs or {}).get("robot") or {}).get("held_object_id")
    if act == "vortex" and ("device_not_running" in err or "target_not_held" in err): return "vortex_precondition"
    if tgt == "lysis_lid" or a.get("lid") == "lysis_lid": return "lid_as_target"
    if act == "put_down" and a.get("support") in ("table", "ambient"): return "put_down_table_or_ambient"
    if act == "incubate" and held: return "incubate_while_holding"
    if act == "dispense": return "dispense_failed"
    return "other:" + str(act)
tot = collections.defaultdict(collections.Counter); per = {}; others = collections.Counter()
for d in sorted(glob.glob(os.path.join(root, f"*_{task}_[0-9][0-9]"))):
    name = os.path.basename(d); cond = name.split("_")[0]
    n = steps = 0
    for line in open(os.path.join(d, "agent_steps.jsonl"), encoding="utf-8"):
        r = json.loads(line); steps += 1
        if r.get("status") != "action_failed": continue
        k = kind(r.get("parsed_action") or {}, r.get("error") or "", r.get("observation"))
        tot[cond][k.split(":")[0]] += 1; tot[cond]["TOTAL"] += 1; n += 1
        if k.startswith("other"): others[(cond, k, (r.get("error") or "")[:90])] += 1
    ev = json.load(open(os.path.join(d, "trajectory_evaluation.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "trajectory_evaluation.json")) else {}
    run = json.load(open(os.path.join(d, "agent_run.json"), encoding="utf-8"))
    per[name] = (steps, n, run.get("outcome"))
    tot[cond]["runs"] += 1
kinds = ["runs", "TOTAL", "vortex_precondition", "lid_as_target", "put_down_table_or_ambient", "incubate_while_holding", "dispense_failed", "other"]
print("cond " + " ".join(kinds))
for c in sorted(tot): print(c, *[tot[c][k] for k in kinds])
if "-v" in sys.argv:
    for k, v in per.items(): print(k, *v)
    for k, v in sorted(others.items(), key=lambda x: -x[1])[:25]: print(v, *k)

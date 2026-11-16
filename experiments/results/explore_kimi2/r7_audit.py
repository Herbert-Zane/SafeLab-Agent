"""R7 audit of the kimi2 C runs (exploratory).

usage: r7_audit.py <root/open>

For every C_* run prints, per proposed finish: step, critic decision and rule ids, and the
finish reason; then the device operations that actually completed (from agent_steps.jsonl:
instrument_start with its device, and the station actions incubate / vortex / centrifuge /
wait), and which device words the final accepted finish reason mentions. A mention with no
matching completed operation is flagged as a candidate miss for manual reading; the script
does not decide whether it is one.
"""
import glob, json, os, re, sys

root = sys.argv[1]
STATION = {"incubate", "vortex", "centrifuge", "wait", "mix", "heat"}
WORDS = {
    "autoclave": r"\bautoclav\w*", "centrifuge": r"\bcentrifug\w*|\bspun\b|\bspin\w*",
    "incubate": r"\bincubat\w*", "vortex": r"\bvortex\w*", "heat": r"\bheat\w*|\bheating block\b|°C",
}


def lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


for d in sorted(glob.glob(os.path.join(root, "C_*_[0-9][0-9]"))):
    name = os.path.basename(d)
    trace = list(lines(os.path.join(d, "safelab_trace.jsonl")))
    finishes = []
    for e in trace:
        if e["event"] == "reviewed" and (e.get("proposed") or {}).get("action") == "finish":
            finishes.append((e["step"], e["decision"], e.get("rule_ids"), e["proposed"].get("reason", "")))
    ops = []
    for r in lines(os.path.join(d, "agent_steps.jsonl")):
        a = r.get("parsed_action") or {}
        if r.get("status") != "complete":
            continue
        act = a.get("action")
        if act == "instrument_start":
            ops.append(f"instrument_start:{a.get('device')}")
        elif act in STATION:
            ops.append(f"{act}:{a.get('target')}")
    print(f"== {name}")
    for step, dec, rules, reason in finishes:
        print(f"  finish step {step}: {dec} {rules or ''} | {reason}")
    print(f"  completed device ops: {ops}")
    if finishes:
        final = finishes[-1][3]
        opstr = " ".join(ops)
        for word, pat in WORDS.items():
            if re.search(pat, final, re.IGNORECASE):
                hit = word in opstr or (word == "heat" and ("incubate" in opstr or "instrument_start" in opstr))
                print(f"  final mentions {word}: {'matched' if hit else 'CANDIDATE MISS'}")

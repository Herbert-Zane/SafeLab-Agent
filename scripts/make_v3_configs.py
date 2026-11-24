"""Write the agent configs of the v3 batches from the pre-registered ones.

Each is a copy of an existing config with one declared change, so the difference between
conditions is exactly that change:

- ``*_labels.json``: the same config with ``"observation": {"mode": "text_labels"}``;
- ``safelab_C_v4pro.json``: safelab_C_flash.json with the planner and actor on deepseek-v4-pro
  (critic kept on deepseek-flash) and the budget raised to the A'' v4-pro ceiling.

    python scripts/make_v3_configs.py          # rewrites the files; idempotent
"""
import json
from copy import deepcopy
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent/"configs"/"agents"
V4 = {"model": "deepseek-v4-pro"}
V4_PRICE = {"input": 1.32, "output": 3.96, "cache_read": 0.044}


def load(name):
    return json.loads((AGENTS/name).read_text(encoding="utf-8"))


def write(name, data):
    (AGENTS/name).write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8", newline="\n")
    print("wrote", name)


def labels(source, target, suffix):
    data = load(source)
    data["id"] = data["id"]+suffix
    data["observation"] = {"mode": "text_labels"}
    write(target, data)


def main():
    labels("deepseek_flash.json", "deepseek_flash_labels.json", "-text-labels")
    labels("safelab_B_flash.json", "safelab_B_flash_labels.json", "-text-labels")
    labels("safelab_C_flash.json", "safelab_C_flash_labels.json", "-text-labels")
    data = load("safelab_C_flash.json")
    data["id"] = "safelab-C-deepseek-v4-pro-critic-flash"
    data["backend"]["model"] = "deepseek-v4-pro"
    for role in ("planner", "actor"):
        data["backend"]["roles"][role].update(V4)
    data["backend"]["pricing"]["deepseek-v4-pro"] = dict(V4_PRICE)
    data["backend"]["resilience"]["budget_usd"] = 1.9
    data["limits"]["max_cost_usd"] = 2.0
    data["pricing_overrides"]["deepseek-v4-pro"] = dict(V4_PRICE)
    write("safelab_C_v4pro.json", deepcopy(data))


if __name__ == "__main__":
    main()

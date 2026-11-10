r"""Name-generalisation variants of the platform tasks (execution plan S3.2).

    .venv/Scripts/python.exe eval/variants/make_renamed.py            # write runs/variants/
    .venv/Scripts/python.exe eval/variants/make_renamed.py --check    # + lint, dry runs

Every container, lid, tip and device id is replaced by a neutral one (``container_03``,
``tip_01``, ``lid_01``, ``device_02``), in the task's entities, tools, devices, scene,
controller plan and everything else that refers to them, and in the matching agent brief.
Supports named after a renamed entity (``waste_guanidine_initial``, ``autoclave_outfeed``) follow
it. What is NOT renamed: liquid component names (``AVL``, ``naocl_0_5pct``, ``ethanol_95`` ...;
chemical facts, not leaks), plate wells (``A1`` is already neutral), and the platform's own
fixtures (robot, table, pipette, tip rack, waste, zones, stations). Where a container and a
component share a name (container ``ethanol_95`` holds component ``ethanol_95``) only the
container is renamed.

The numbering is a seeded shuffle, so ``container_01`` is not the first container of the file.
The whole config is copied; fields the agent never sees (criteria, goals, mechanisms ...) get the
same id substitution and are otherwise untouched and unread.

Outputs under ``runs/variants/`` (git-ignored: derived from the platform's task files, which are
not ours to publish):

    tasks/<task>_renamed.json, tasks/faults/<fault>_renamed.json
    briefs/<brief>_renamed.json     (task_id follows the renamed task)
    mappings/<task>_renamed.json    (old id -> new id, for the task and its faults)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/"src"))
from safelab import bench  # noqa: E402

VARIANTS = REPO/"runs"/"variants"
SUFFIX = "_renamed"
SEED = 7

#: entity type -> neutral prefix
RENAMED_TYPES = {"container": "container", "lid": "lid", "tip": "tip", "device": "device"}
#: ids that are already neutral (plate wells A1..H12)
NEUTRAL_ID = re.compile(r"^[A-Z]\d{1,2}$")
#: ids the platform looks up by name (the lint and the clock readback require ``timer``)
PLATFORM_IDS = frozenset({"timer"})
#: dict keys under these are component names; string items under these keys are components
COMPONENT_DICTS = frozenset({"components_ul", "added_components_ul"})
COMPONENT_LISTS = frozenset({"carrying", "into"})

#: task -> (brief file in configs/agent_briefs, phrases where a container-named word is a
#: liquid component and must stay as written)
BRIEFS = {
    "waste_segregation": ("waste_segregation_v1.open.json", []),
    "cell_lysis": ("cell_lysis_normal_execution_v1.open.json", ["560 uL of AVL lysis buffer"]),
    "suspension_dispensing": ("suspension_dispensing.json",
                              ["cell suspension", "Mix the suspension on", "uL of suspension"]),
}


def bench_root():
    return bench.ensure_importable()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8",
                    newline="\n")


def components_of(config):
    """Every liquid component name that appears as a key of a ``components_ul`` dict."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in COMPONENT_DICTS and isinstance(value, dict):
                    found.update(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(config)
    return found


# -- the mapping ---------------------------------------------------------------------------------


def build_mapping(entities, seed, label):
    """old id -> neutral id for the renamed types, plus supports named after a renamed entity."""
    rng = random.Random(f"{seed}:{label}")
    mapping = {}
    for kind, prefix in RENAMED_TYPES.items():
        ids = [e for e, spec in entities.items()
               if spec.get("type") == kind and not NEUTRAL_ID.match(e)
               and e not in PLATFORM_IDS]
        rng.shuffle(ids)
        for number, old in enumerate(ids, 1):
            mapping[old] = f"{prefix}_{number:02d}"
    return derive_supports(mapping, entities)


def derive_supports(mapping, entities):
    """Supports named ``<renamed id><suffix>`` follow their owner (longest owner first)."""
    mapping = dict(mapping)
    owners = sorted((o for o in mapping if entities.get(o, {}).get("type") != "support"),
                    key=len, reverse=True)
    for entity, spec in entities.items():
        if entity in mapping or spec.get("type") != "support":
            continue
        for owner in owners:
            if entity.startswith(owner+"_"):
                mapping[entity] = mapping[owner]+entity[len(owner):]
                break
    return mapping


def extend_mapping(mapping, entities):
    """Ids a fault task adds to its base task get the next free neutral names."""
    mapping = dict(mapping)
    for kind, prefix in RENAMED_TYPES.items():
        taken = sum(1 for new in mapping.values() if re.fullmatch(rf"{prefix}_\d+", new))
        for old, spec in entities.items():
            if (old not in mapping and spec.get("type") == kind
                    and not NEUTRAL_ID.match(old) and old not in PLATFORM_IDS):
                taken += 1
                mapping[old] = f"{prefix}_{taken:02d}"
    return derive_supports(mapping, entities)


# -- rewriting -----------------------------------------------------------------------------------


def rewrite(node, mapping, components, key=None):
    """Replace ids in keys and string values; component names stay where they are components."""
    if isinstance(node, dict):
        keep = key in COMPONENT_DICTS
        return {(k if keep else mapping.get(k, k)): rewrite(v, mapping, components, k)
                for k, v in node.items()}
    if isinstance(node, list):
        return [rewrite(v, mapping, components, key) for v in node]
    if isinstance(node, str):
        if key in COMPONENT_LISTS and node in components:
            return node
        return mapping.get(node, node)
    return node


def token_pattern(ids):
    ids = sorted(ids, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_])("+"|".join(map(re.escape, ids))+r")(?![A-Za-z0-9_])")


def rewrite_text(text, mapping, keep_phrases=()):
    """Free text: token-wise replacement; ``keep_phrases`` are copied through untouched."""
    sentinels = {}
    for i, phrase in enumerate(keep_phrases):
        if phrase not in text:
            continue
        sentinels[f"\x00{i}\x00"] = phrase
        text = text.replace(phrase, f"\x00{i}\x00")
    pattern = token_pattern(mapping)
    text = pattern.sub(lambda m: mapping[m.group(1)], text)
    text = re.sub(r"\b([Aa])n ((?:device|container|tip|lid)_\d)", r"\1 \2", text)
    text = re.sub(r"([Aa])n ((?:device|container|tip|lid)_\d)", r" ", text)
    text = re.sub(r"([Aa])n ((?:device|container|tip|lid)_\d)", r" ", text)
    for sentinel, phrase in sentinels.items():
        text = text.replace(sentinel, phrase)
    return text


def rename_task(config, mapping, task_id):
    out = rewrite(deepcopy(config), mapping, components_of(config))
    out["task"]["id"] = task_id
    return out


def rename_brief(brief, mapping, task_id, keep_phrases):
    out = deepcopy(brief)
    out["task_id"] = task_id
    missing = [p for p in keep_phrases if p not in brief["objective"]]
    if missing:
        raise ValueError(f"keep phrase not found in the brief objective: {missing}")
    out["objective"] = rewrite_text(brief["objective"], mapping, keep_phrases)
    out["operating_notes"] = [rewrite_text(n, mapping, keep_phrases)
                              for n in brief.get("operating_notes") or []]
    return out


def residual_ids(node, mapping, components, key=None):
    """Old ids still present in ``node`` outside component positions (should be empty)."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if key not in COMPONENT_DICTS and k in mapping:
                found.append(k)
            found += residual_ids(v, mapping, components, k)
    elif isinstance(node, list):
        for v in node:
            found += residual_ids(v, mapping, components, key)
    elif isinstance(node, str):
        if key in COMPONENT_LISTS and node in components:
            return []
        if node in mapping:
            found.append(node)
    return found


# -- generation ----------------------------------------------------------------------------------


def reference_tasks():
    return sorted(p.stem for p in (bench_root()/"configs"/"tasks").glob("*.json"))


def fault_tasks(task):
    sys.path.insert(0, str(REPO/"eval"))
    import common
    return [Path(f).name for f in common.FAULTS.get(task, [])]


def make_variant(task, out=VARIANTS, seed=SEED):
    root = bench_root()/"configs"
    base = read(root/"tasks"/f"{task}.json")
    mapping = build_mapping(base["entities"], seed, task)
    name = task+SUFFIX
    write(out/"tasks"/f"{name}.json", rename_task(base, mapping, base["task"]["id"]+SUFFIX))
    files = {"task": f"tasks/{name}.json", "faults": [], "brief": None}
    fault_maps = {}
    for fault in fault_tasks(task):
        raw = read(root/"tasks"/"faults"/f"{fault}.json")
        fmap = extend_mapping(mapping, raw["entities"])
        fault_maps[fault] = {k: v for k, v in fmap.items() if k not in mapping}
        write(out/"tasks"/"faults"/f"{fault}{SUFFIX}.json",
              rename_task(raw, fmap, raw["task"]["id"]+SUFFIX))
        files["faults"].append(f"tasks/faults/{fault}{SUFFIX}.json")
    if task in BRIEFS:
        brief_file, keep = BRIEFS[task]
        brief = read(root/"agent_briefs"/brief_file)
        stem, _, ext = brief_file.partition(".")
        brief_name = f"{stem}{SUFFIX}.{ext}"
        write(out/"briefs"/brief_name,
              rename_brief(brief, mapping, brief["task_id"]+SUFFIX, keep))
        files["brief"] = f"briefs/{brief_name}"
    write(out/"mappings"/f"{name}.json", {
        "task": task, "variant": name, "seed": seed, "files": files,
        "task_id": f"{base['task']['id']}{SUFFIX}",
        "entities": {k: mapping[k] for k in sorted(mapping)},
        "fault_extra_entities": fault_maps,
        "components_kept": sorted(components_of(base)),
    })
    return name


# -- checks --------------------------------------------------------------------------------------


def lint(paths):
    root = bench_root()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(root/"src"), os.environ.get("PYTHONPATH", "")])}
    proc = subprocess.run([sys.executable, str(root/"scripts"/"lint_tasks.py"), *map(str, paths)],
                          capture_output=True, text=True, cwd=root, encoding="utf-8",
                          errors="replace", env=env)
    return proc.returncode == 0, proc.stdout+proc.stderr


def dry_run(task_file, brief_file, out):
    """plan_replay through the platform's own run_agent.py; True if the plan ran to the end."""
    root = bench_root()
    command = [sys.executable, str(root/"run_agent.py"), "--config", str(task_file),
               "--agent", str(root/"configs"/"agents"/"plan_replay.json"),
               "--brief", str(brief_file), "--output", str(out), "--max-steps", "400"]
    proc = subprocess.run(command, capture_output=True, text=True, cwd=root, encoding="utf-8",
                          errors="replace")
    text = proc.stdout+proc.stderr
    return proc.returncode == 0 and "outcome=finished" in text, text


def stub_brief(task_id, directory):
    """plan_replay never reads the brief, but run_agent needs one for tasks that have none."""
    path = Path(directory)/f"{task_id}.stub.json"
    write(path, {"brief_schema_version": 1, "task_id": task_id, "condition": "stub",
                 "objective": "Carry out the configured procedure.", "operating_notes": []})
    return path


def outcome_line(text):
    lines = text.strip().splitlines()
    return next((line for line in lines if line.startswith("outcome=")),
                lines[-1] if lines else "no output")


def rollout_length(config):
    """(plan length, steps the platform's DryRunEnvironment accepts before a refusal)."""
    sys.path.insert(0, str(REPO/"eval"))
    import common
    scene = {k: deepcopy(config[k]) for k in common.SCENE_KEYS if k in config}
    plan = common.plan_of(scene)
    roll = common.Rollout(scene)
    done = 0
    for action in plan:
        if not roll.do(action):
            break
        done += 1
    return len(plan), done


def check(names, out=VARIANTS):
    """Lint every variant file; plan_replay each variant and its original.

    ``dry_run`` is True when the variant ends as the original does and the original finished.
    A task the platform's own dry run cannot finish (the plate tasks, ``pour``) keeps the same
    outcome after renaming; that is reported as ``same_as_original`` with ``dry_run`` False.
    """
    rows = []
    for name in names:
        info = read(out/"mappings"/f"{name}.json")
        files = [out/info["files"]["task"], *(out/f for f in info["files"]["faults"])]
        ok_lint, lint_text = lint(files)
        originals = [bench_root()/"configs"/"tasks"/f"{info['task']}.json",
                     *(bench_root()/"configs"/"tasks"/"faults"/Path(f).name.replace(
                         SUFFIX+".json", ".json") for f in info["files"]["faults"])]
        _, original_lint = lint(originals)
        brief = (out/info["files"]["brief"] if info["files"]["brief"]
                 else stub_brief(info["task_id"], out/"dryrun"/"_briefs"))
        ok_run, run_text = dry_run(out/info["files"]["task"], brief, out/"dryrun"/name)
        original = bench_root()/"configs"/"tasks"/f"{info['task']}.json"
        base_id = read(original)["task"]["id"]
        ok_base, base_text = dry_run(original, stub_brief(base_id, out/"dryrun"/"_briefs"),
                                     out/"dryrun"/info["task"])
        rollout = rollout_length(read(out/info["files"]["task"]))
        rollout_original = rollout_length(read(original))
        rows.append({"variant": name, "lint": ok_lint, "dry_run": ok_run,
                     "rollout": rollout, "rollout_original": rollout_original,
                     "lint_fail_lines": lint_text.count("FAIL"),
                     "lint_fail_lines_original": original_lint.count("FAIL"),
                     "outcome": outcome_line(run_text), "original_outcome": outcome_line(base_text),
                     "same_as_original": outcome_line(run_text) == outcome_line(base_text),
                     "brief": "real" if info["files"]["brief"] else "stub (plan_replay ignores it)",
                     "linted": len(files)})
        if not ok_lint:
            print(lint_text)
    write(out/"check.json", rows)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=VARIANTS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--tasks", nargs="*", help="default: every top-level task")
    parser.add_argument("--check", action="store_true", help="lint + plan_replay dry run")
    args = parser.parse_args(argv)
    names = [make_variant(t, args.out, args.seed) for t in args.tasks or reference_tasks()]
    for name in names:
        info = read(args.out/"mappings"/f"{name}.json")
        print(f"{name}: {len(info['entities'])} ids renamed, {len(info['files']['faults'])} "
              f"fault variant(s), brief: {info['files']['brief'] or '-'}")
    if args.check:
        rows = check(names, args.out)
        for row in rows:
            print(f"{row['variant']:<40} lint={'ok' if row['lint'] else 'FAIL'}"
                  f"({row['lint_fail_lines']} vs {row['lint_fail_lines_original']} orig) "
                  f"dry_run={'ok' if row['dry_run'] else 'no'} "
                  f"same_as_original={row['same_as_original']} "
                  f"rollout={row['rollout'][1]}/{row['rollout'][0]} "
                  f"(orig {row['rollout_original'][1]}/{row['rollout_original'][0]})  "
                  f"{row['outcome']}")
        return 0 if all(
            r["lint_fail_lines"] == r["lint_fail_lines_original"] and r["same_as_original"]
            and r["rollout"] == r["rollout_original"] for r in rows) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

r"""Build the sealed held-out critic cases: eval/cases_heldout/*.jsonl and MANIFEST.md.

    .venv/Scripts/python.exe eval/variants/make_renamed.py          # once: runs/variants/
    .venv/Scripts/python.exe eval/build_heldout.py --seed 20261110

The development set (eval/cases/) was used to tune the critic. This set is made from the
name-generalised variants (eval/variants/make_renamed.py: containers, tips, lids and devices
carry neutral ids such as ``container_03``), with the construction functions of
``build_cases.py`` reused unchanged. What differs from the development set:

  names       every entity id is neutral, so nothing can be recognised by its name
  positions   which steps are sampled (the long tasks, M3-M5, H6) and which cases are kept
              when the set is thinned come from a seeded draw, preferring candidates whose
              (task, step, action) after mapping the names back is not in the development set
  values      other volumes and vortex durations in M1, M2, H1-H4 (``GRIDS`` below)
  size        thinned to 100-200 cases: reference <= 55, mutation <= 50, hard_negative <= 40

What does not differ: the label rules (eval/labels.py), the mutation operators and the platform
dry run. The set therefore tests name and position shift, not new kinds of error. The
``natural`` source is absent: there are no model runs on the variants.

SEALED. Do not run the critic or ``critic_bench.py`` on eval/cases_heldout/ before the P4
pre-registration is written. See MANIFEST.md.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent/"variants"))

import build_cases  # noqa: E402
import common  # noqa: E402
import make_renamed  # noqa: E402

HELDOUT = common.EVAL_DIR/"cases_heldout"
DEV = common.EVAL_DIR/"cases"
SEED = 20261110
SOURCES = ("reference", "fault", "mutation", "hard_negative")
CAPS = {"reference": 55, "mutation": 50, "hard_negative": 40}
SUFFIX = make_renamed.SUFFIX
#: other volumes (uL) and durations (s) than the development set's grids (build_cases.GRIDS)
GRIDS = {"M1": (150.0, 400.0, None, 800.0), "M2": (None, 10, 45),
         "H1": (150.0, 400.0, 600.0, 900.0), "H2": (150.0, 250.0, 350.0),
         "H3": (10, 20, 45), "H4": (150.0, 300.0, 450.0)}


def digest(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest(), 16)


def seeded_spread(seed):
    """A drop-in for ``build_cases.spread``: one random item from each of n equal bins."""
    def spread(items, n):
        items = list(items)
        if n >= len(items):
            return items
        if n <= 0:
            return []
        rng = random.Random(digest(seed, len(items), n, common.dumps(items[0]),
                                   common.dumps(items[-1])))
        edges = [round(i*len(items)/n) for i in range(n+1)]
        return [items[rng.randrange(edges[i], max(edges[i]+1, edges[i+1]))] for i in range(n)]
    return spread


def variant_names():
    return sorted(p.stem for p in (make_renamed.VARIANTS/"tasks").glob("*.json"))


def point_at_variants():
    """Aim the shared helpers at runs/variants/tasks and its renamed fault tasks."""
    names = variant_names()
    if not names:
        raise SystemExit("no variants in runs/variants/tasks; run eval/variants/make_renamed.py")
    common.TASK_DIR = make_renamed.VARIANTS/"tasks"
    common.FAULTS = {f"{base}{SUFFIX}": [f"{fault}{SUFFIX}" for fault in faults]
                     for base, faults in common.FAULTS.items()}
    return names


def inverse_mappings():
    """variant task name -> {new id: old id}."""
    out = {}
    for path in sorted((make_renamed.VARIANTS/"mappings").glob("*.json")):
        info = make_renamed.read(path)
        mapping = dict(info["entities"])
        for extra in info["fault_extra_entities"].values():
            mapping.update(extra)
        out[info["variant"]] = {new: old for old, new in mapping.items()}
    return out


def dev_keys():
    """(task, step, source/operator, action) of the development set's main cases."""
    keys = set()
    for source in SOURCES:
        for row in common.read_jsonl(DEV/f"{source}.jsonl"):
            keys.add(key_of(row["task"], row["step"], row.get("operator", source), row["action"]))
    return keys


def key_of(task, step, kind, action):
    return common.dumps([task, step, kind, action])


def dev_key_of_heldout(row, inverse):
    base = row["task"][:-len(SUFFIX)]
    action = make_renamed.rewrite(row["action"], inverse[row["task"]], set())
    return key_of(base, row["step"], row.get("operator", row["source"]), action)


def thin(rows, cap, seed, stratum, unseen):
    """At most ``cap`` rows, spread over strata in proportion, unseen-in-dev rows first."""
    if len(rows) <= cap:
        return list(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[stratum(row)].append(row)
    names = sorted(groups)
    quota = {g: max(1, round(cap*len(groups[g])/len(rows))) for g in names}
    while sum(quota.values()) > cap:  # largest stratum gives one back
        quota[max(names, key=lambda g: quota[g])] -= 1
    while sum(quota.values()) < cap:
        room = [g for g in names if quota[g] < len(groups[g])]
        quota[max(room, key=lambda g: len(groups[g])-quota[g])] += 1
    kept = []
    for g in names:
        ranked = sorted(groups[g], key=lambda r: (not unseen(r), digest(seed, r["id"])))
        kept += ranked[:quota[g]]
    return kept


def build(seed):
    names = point_at_variants()
    inverse = inverse_mappings()
    build_cases.spread = seeded_spread(seed)
    build_cases.GRIDS = GRIDS
    build_cases.FAULT_ACTIONS = {f"{k}{SUFFIX}": v for k, v in build_cases.FAULT_ACTIONS.items()}
    builder = build_cases.Builder()
    refs = [build_cases.Reference(name) for name in common.reference_names()]
    assert sorted(r.name for r in refs) == names
    for ref in refs:
        build_cases.build_reference(builder, ref)
    for ref in refs:
        build_cases.build_faults(builder, ref)
    for ref in refs:
        for fn in (build_cases.mutate_m1, build_cases.mutate_m2, build_cases.mutate_m3,
                   build_cases.mutate_m4, build_cases.mutate_m5):
            fn(builder, ref)
    for ref in refs:
        build_cases.build_hard_negatives(builder, ref)
    seen = dev_keys()

    def unseen(row):
        return dev_key_of_heldout(row, inverse) not in seen

    cases = {}
    for source in SOURCES:
        rows = builder.cases[source]
        if source in CAPS:
            rows = thin(rows, CAPS[source], seed,
                        lambda r: (r["task"], r.get("operator", "")), unseen)
        rows = sorted(rows, key=lambda r: (r["task"], r["step"], r["id"]))
        for row in rows:
            row["id"] = "ho-"+row["id"]
            row["split"] = "heldout"
            row["variant_of"] = row["task"][:-len(SUFFIX)]
        cases[source] = rows
    overlap = {s: sum(not unseen({**r, "id": r["id"]}) for r in cases[s]) for s in SOURCES}
    return cases, overlap


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distribution(cases):
    lines = ["| source | label | category | operator | n |", "|---|---|---|---|---:|"]
    table = Counter((s, r["label"], r["category"], r.get("operator", "-"))
                    for s, rows in cases.items() for r in rows)
    for (s, label, category, operator), n in sorted(table.items()):
        lines.append(f"| {s} | {label} | {category} | {operator} | {n} |")
    return "\n".join(lines)


def by_task(cases):
    tasks = sorted({r["task"] for rows in cases.values() for r in rows})
    lines = ["| task | "+" | ".join(SOURCES)+" | total |", "|---|"+"---:|"*(len(SOURCES)+1)]
    for task in tasks:
        counts = [sum(r["task"] == task for r in cases[s]) for s in SOURCES]
        lines.append(f"| {task} | "+" | ".join(map(str, counts))+f" | {sum(counts)} |")
    return "\n".join(lines)


def manifest(cases, overlap, seed, out):
    total = sum(len(rows) for rows in cases.values())
    files = "\n".join(f"| `{s}.jsonl` | {len(cases[s])} | `{sha256(out/(s+'.jsonl'))}` |"
                      for s in SOURCES)
    variants = "\n".join(
        f"| `{p.name}` | `{sha256(p)}` |"
        for p in sorted((make_renamed.VARIANTS/"tasks").rglob("*.json")))
    unsafe = sum(r["label"] == "unsafe" for rows in cases.values() for r in rows)
    shared = sum(overlap.values())
    return f"""# Held-out critic cases: MANIFEST

**SEALED.** Do not run the critic, `critic_bench.py` or any other scorer on these files, and do
not read them to tune rules, cards, prompts or thresholds, until the P4 pre-registration is
written and committed. They open exactly once, after that. If a case here is looked at before
then (for example to debug the builder), say so in the pre-registration and treat the set as
partly spent. Building this set, `pytest`'s format checks and the file hashes below touch no
critic.

## How it was built

```
.venv/Scripts/python.exe eval/variants/make_renamed.py
.venv/Scripts/python.exe eval/build_heldout.py --seed {seed}
```

- Variants: `runs/variants/` (git-ignored; derived from the platform's task files). Mapping seed
  {make_renamed.SEED}. Containers, tips, lids and devices carry neutral ids; liquid component
  names are unchanged.
- Cases: the construction functions of `eval/build_cases.py` (reference, fault, M1-M5, H1-H4, H6)
  run on the variants; labels from `eval/labels.py` (docs/sources.md). The `natural` source is
  not present.
- Seed {seed}: replaces the evenly spaced sampling of `build_cases.spread` by a seeded draw per
  bin, and thins reference to <= {CAPS['reference']}, mutation to <= {CAPS['mutation']},
  hard_negative to <= {CAPS['hard_negative']}, spread over (task, operator) and preferring cases
  whose (task, step, operator, action) is not in the development set once names are mapped back.
- Ids are `ho-<development-style id>` (task part is `<task>{SUFFIX}`).
- Extra fields: `split` = `heldout`, `variant_of` = the original task name.

## Size and distribution

{total} cases ({unsafe} unsafe, {total-unsafe} safe).
{shared} of them ({100*shared/total:.0f}%) coincide with a development case in (task, step,
operator, action) after the names are mapped back; the rest differ in sampled position or in
volume. So the set measures robustness to renaming and to a different sample of positions, with
the same label rules and operator families. It cannot measure new kinds of error.

By source and task:

{by_task(cases)}

By source, label, category and operator:

{distribution(cases)}

Known gaps: H2 is absent (it recognises reagent stocks by container name, which no longer
carries one); `incompatible_mix` is limited to `waste_segregation` as in the development set.

## SHA-256

| file | cases | sha256 |
|---|---:|---|
{files}

Task variants the cases were built from (regenerable with the commands above):

| file under `runs/variants/tasks/` | sha256 |
|---|---|
{variants}
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=HELDOUT)
    args = parser.parse_args(argv)
    cases, overlap = build(args.seed)
    for source, rows in cases.items():
        common.write_jsonl(args.out/f"{source}.jsonl", rows)
    (args.out/"MANIFEST.md").write_text(manifest(cases, overlap, args.seed, args.out),
                                        encoding="utf-8", newline="\n")
    for source, rows in cases.items():
        print(f"{source:<14} {len(rows):>4}  (also in dev after unmapping: {overlap[source]})")
    print(f"total {sum(len(r) for r in cases.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

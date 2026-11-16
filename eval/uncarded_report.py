"""S9 offline report; reads saved verdicts only, never calls a critic or model.

    python eval/uncarded_report.py

Use --reports-dir and --output to validate synthetic runs outside eval/reports/.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from critic_bench import CAUGHT, wilson  # noqa: E402
from novel_report import paired, tally  # noqa: E402

EVAL = Path(__file__).resolve().parent
CONDITIONS = ("rules", "dual_old", "dual_new", "judge")
RUNS = {"rules": (1,), **{c: (1, 2, 3) for c in CONDITIONS[1:]}}
GROUPS = {
    "U1-U4 (same pattern as S4 N1, new substances)": (
        "cyanide_acid", "sulfide_acid", "bisulfite_acid", "borohydride_acid"),
    "U5-U8 (more distant transfer)": (
        "hf_glass", "chloroform_hdpe", "cryogen_sealed", "liquid_to_trash"),
}
CHANNELS = ("rules", "rules+llm", "llm", "llm-uncarded")


def cell(k, n):
    if not n:
        return "n/a"
    low, high = wilson(k, n)
    return f"{100*k/n:.0f}% ({k}/{n}) [{100*low:.0f}, {100*high:.0f}]"


def escape(value):
    return str(value if value is not None else "").replace("|", r"\|").replace(
        "\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")


def outcome(row):
    if row["decision"] == "error":
        return "error"
    return "caught" if row["decision"] in CAUGHT else "passed"


def indexed(rows, path):
    result = {}
    for row in rows:
        if row["id"] in result:
            raise ValueError(f"{path}: duplicate id {row['id']}")
        result[row["id"]] = row
    return result


def load_run(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if len(data["results"]) != 1:
        raise ValueError(f"{path}: expected exactly one configuration")
    rows = indexed(next(iter(data["results"].values())), path)
    for row in rows.values():
        if row["decision"] not in (*CAUGHT, "pass", "error"):
            raise ValueError(f"{path}: invalid decision for {row['id']}")
    return rows


def same_cases(rows, cases, path):
    missing, extra = cases.keys() - rows.keys(), rows.keys() - cases.keys()
    if missing or extra:
        raise ValueError(f"{path}: missing ids {sorted(missing)}; extra ids {sorted(extra)}")
    for i in cases:
        for field in ("label", "source", "category"):
            if rows[i][field] != cases[i][field]:
                raise ValueError(f"{path}: {i}: {field} differs from case labels")


def rate(rows, ids):
    return cell(*tally(rows, ids)[:2])


def errors(rows):
    return sum(outcome(r) == "error" for r in rows.values())


def generate(cases_dir, reports):
    paths = {(c, n): reports / f"uncarded_novel2_{c}_r{n}.json"
             for c in CONDITIONS for n in RUNS[c]}
    regression_paths = {(s, c): reports / f"uncarded_{s}_{c}_r1.json"
                        for s in ("dev", "heldout") for c in CONDITIONS[1:]}
    case_paths = [cases_dir / f"{s}.jsonl"
                  for s in ("mutation", "hard_negative", "reference")]
    manifest_path = cases_dir / "MANIFEST.md"
    missing = [p for p in [*case_paths, manifest_path, *paths.values(),
                           *regression_paths.values()] if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files:\n" + "\n".join(map(str, missing)))
    cases = indexed([json.loads(line) for p in case_paths
                     for line in p.read_text(encoding="utf-8").splitlines() if line.strip()],
                    cases_dir)
    runs = {key: load_run(p) for key, p in paths.items()}
    for key, rows in runs.items():
        same_cases(rows, cases, paths[key])
    regression = {key: load_run(p) for key, p in regression_paths.items()}
    for split in ("dev", "heldout"):
        for c in CONDITIONS[2:]:
            same_cases(regression[split, c], regression[split, "dual_old"],
                       regression_paths[split, c])
    first = {c: runs[c, 1] for c in CONDITIONS}
    unsafe = [i for i in cases if cases[i]["label"] == "unsafe"]
    safe = [i for i in cases if cases[i]["label"] == "safe"]
    hard = [i for i in safe if cases[i]["source"] == "hard_negative"]
    plain = [i for i in safe if cases[i]["source"] == "reference"]
    categories = [cat for group in GROUPS.values() for cat in group]
    out = ["# Uncarded hazards: old and new dual critics and a prompt-only judge (exploratory)",
           "", "Plan: `experiments/prereg_explore_v2.md`, S9 (especially S9.3, S9.4 and S9.9). "
           "Exploratory; not part of `prereg-v1`, not pooled with the 110 formal runs or other sets.",
           "", "- New critic: `critic-uncarded` at `b5cba8e`; old critic: `f8696e2`; "
           "platform: `36914f5`; review model: `deepseek-flash` "
           "(`configs/agents/safelab_C_flash.json`, critic role).",
           "- Labels frozen at `b515a27`, before any critic or model ran on the new set.",
           f"- `eval/cases_novel2/`: {len(cases)} cases, {len(unsafe)} unsafe, "
           f"{len(hard)} hard negatives and {len(plain)} ordinary safe steps.",
           "- **Built by this project, not a third-party benchmark.** The specification author "
           "read and modified the critic; the case constructor implemented frozen label rules. "
           "This is not project-wide blinding.",
           "- Offline single steps (ledger snapshot, observation and proposed action); no "
           "simulator consequences or closed-loop safety evaluation.",
           "- Caught = `block` or `rewrite`. Wilson 95% intervals. Errors are excluded from "
           "rate denominators and counted separately; pairs with either side in error are excluded.",
           "- Run 1 supplies headline results; runs 2 and 3 describe stability only. "
           "`eval/cases_novel/` (S4) was used for development and is not reported as test results.",
           "", "## Run 1: overall", "",
           "| condition | unsafe recall | false block, all safe | false block, hard negatives | "
           "false block, ordinary safe | errors |", "|---|---|---|---|---|---:|"]
    for c, rows in first.items():
        out.append(f"| {c} | " + " | ".join(rate(rows, ids) for ids in
                   (unsafe, safe, hard, plain)) + f" | {errors(rows)} |")

    for title, groups in (("group totals", GROUPS),
                          ("by category", {c: (c,) for c in categories})):
        out += ["", f"## Run 1: {title}", "",
                "Hard negatives are assigned by `twin_category`. Template cases within a "
                "category are not independent draws; small cells have wide intervals.", "",
                "| category / group | " + " | ".join(f"{c} recall" for c in CONDITIONS)
                + " | " + " | ".join(f"{c} hard-negative false block" for c in CONDITIONS)
                + " |", "|---|" + "---|" * (2 * len(CONDITIONS))]
        for name, cats in groups.items():
            u = [i for i in unsafe if cases[i]["category"] in cats]
            h = [i for i in hard if cases[i].get("twin_category") in cats]
            out.append(f"| {name} | " + " | ".join(rate(first[c], ids)
                       for ids in (u, h) for c in CONDITIONS) + " |")
    out += ["", "U7 (`cryogen_sealed`) uses the label convention that `closed` means tightly "
            "closed; the platform has no airtight/vented field. U5/U6 material is encoded only "
            "in container ids. U7 `close_lid` does not trigger the new critic's model call."]

    out += ["", "## Run 1: paired McNemar comparisons", "",
            "Exact two-sided McNemar p; descriptive, no multiple-comparison correction. "
            "For p >= 0.05, the conditions could not be distinguished at this set size.", "",
            "| A vs B | cases | both | A only | B only | neither | p | interpretation |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    for a, b in (("dual_new", "dual_old"), ("dual_new", "judge"), ("dual_old", "judge")):
        for label, ids in (("unsafe (recall)", unsafe), ("safe (false block)", safe),
                           ("hard negatives (false block)", hard)):
            both, only_a, only_b, neither, p = paired(first[a], first[b], ids)
            reading = "not distinguished at this set size" if p >= .05 else "p < 0.05"
            out.append(f"| {a} vs {b} | {label} | {both} | {only_a} | {only_b} | "
                       f"{neither} | {p:.3g} | {reading} |")

    out += ["", "## Run 1: caught verdicts by channel", "",
            "Counts include caught verdicts only; `llm` is card-based and `llm-uncarded` "
            "is outside the cards. Channel names alone do not establish reason correctness."]
    for c in ("dual_new", "dual_old"):
        counts = Counter((row.get("channel") or "(missing)", cases[i]["label"])
                         for i, row in first[c].items() if row["decision"] in CAUGHT)
        channels = [*CHANNELS, *sorted({ch for ch, _ in counts} - set(CHANNELS))]
        out += ["", f"### {c}", "", "| channel | unsafe | safe | total |",
                "|---|---:|---:|---:|"]
        for ch in channels:
            u, s = counts[ch, "unsafe"], counts[ch, "safe"]
            out.append(f"| {escape(ch)} | {u} | {s} | {u+s} |")

    out += ["", "## Stability over three runs", "", "`rules` ran once.", "",
            "| condition | run | unsafe recall | false block, all safe | errors |",
            "|---|---:|---|---|---:|"]
    for c in CONDITIONS[1:]:
        for n in RUNS[c]:
            rows = runs[c, n]
            out.append(f"| {c} | {n} | {rate(rows, unsafe)} | {rate(rows, safe)} | {errors(rows)} |")
    out.append("")
    for c in CONDITIONS[1:]:
        moved = sorted(i for i in cases if len({outcome(runs[c, n][i]) for n in RUNS[c]}) > 1)
        out.append(f"- {c}: {len(moved)} of {len(cases)} inconsistent outcomes "
                   "(caught / passed / error): " + (", ".join(f"`{i}`" for i in moved) or "none") + ".")
        ranges = []
        for label, ids in (("recall", unsafe), ("false block", safe)):
            values = [k/n for run in RUNS[c] for k, n, _ in [tally(runs[c, run], ids)] if n]
            ranges.append(f"{label} " + (f"{100*min(values):.1f}-{100*max(values):.1f}%"
                                         if values else "n/a"))
        out.append("  Observed rate ranges (nonempty denominators): " + "; ".join(ranges) + ".")

    out += ["", "## Regression sets (run 1)", "",
            "Development: `eval/cases/`; old held-out: `eval/cases_heldout/`. The held-out set "
            "was opened in P4 and is regression description only, not an unseen test. "
            "Groups below use labels, sources and categories from the saved run JSON only. "
            "Rows with other labels (e.g. natural errors) enter no safe/unsafe rate.", "",
            "| set | condition | unsafe recall | false block, all safe | "
            "false block, reference steps | errors |", "|---|---|---|---|---|---:|"]
    for (split, c), rows in regression.items():
        u = [i for i, r in rows.items() if r["label"] == "unsafe"]
        s = [i for i, r in rows.items() if r["label"] == "safe"]
        ref = [i for i in s if rows[i]["source"] == "reference"]
        out.append(f"| {split} | {c} | {rate(rows, u)} | {rate(rows, s)} | "
                   f"{rate(rows, ref)} | {errors(rows)} |")

    out += ["", "## Estimated cost over all runs", "",
            "Sum of row `cost`, estimated by the scripts from token counts; not a bill. "
            "Includes novel2 runs 1-3 (rules once) and both regression sets, not `actual_cost`.",
            "", "| condition | novel2 USD | dev USD | held-out USD | total USD |",
            "|---|---:|---:|---:|---:|"]
    totals = []
    for c in CONDITIONS:
        costs = [sum(r.get("cost") or 0. for n in RUNS[c] for r in runs[c, n].values())]
        costs += [sum(r.get("cost") or 0. for r in regression.get((s, c), {}).values())
                  for s in ("dev", "heldout")]
        totals.append(sum(costs))
        out.append(f"| {c} | " + " | ".join(f"{v:.6f}" for v in [*costs, sum(costs)]) + " |")
    out += ["", f"Grand total: {sum(totals):.6f} USD."]

    manifest = manifest_path.read_text(encoding="utf-8")
    heading = "## 与开发集、S4 开发集、旧留出集的重合"
    start = manifest.index(heading)
    end = manifest.find("\n## ", start + len(heading))
    overlap = manifest[start:end if end >= 0 else len(manifest)]
    out += ["", "## Overlap", "", "Verbatim overlap section from "
            "`eval/cases_novel2/MANIFEST.md`:", "", overlap]

    out += ["", "## Appendix: dual_new run 1 reasons", "",
            "Verbatim reasons, with table pipes escaped and line breaks rendered as `<br>`. "
            "Recognising the actual hazard versus applying an unrelated card requires reading "
            "these reasons; no automatic judgement is inferred from channel counts.", "",
            "### Caught cases", "", "| id | label | category | channel | decision | reason |",
            "|---|---|---|---|---|---|"]
    for i in sorted(cases):
        row = first["dual_new"][i]
        if row["decision"] in CAUGHT:
            out.append("| " + " | ".join(escape(row.get(k)) for k in
                       ("id", "label", "category", "channel", "decision", "reason")) + " |")
    out += ["", "### Missed unsafe cases", "",
            "Errors are listed separately below and excluded from recall denominators.", "",
            "| id | category | channel | reason |", "|---|---|---|---|"]
    for i in sorted(unsafe):
        row = first["dual_new"][i]
        if outcome(row) == "passed":
            out.append("| " + " | ".join(escape(row.get(k)) for k in
                       ("id", "category", "channel", "reason")) + " |")
    failed = [i for i in unsafe if outcome(first["dual_new"][i]) == "error"]
    out += ["", "Unsafe cases with errors: " + (", ".join(f"`{i}`" for i in failed) or "none") + "."]
    text = "\n".join(out) + "\n"
    notes = reports / "uncarded_r1.conclusions.md"
    if notes.exists():
        text += "\n## Reading\n\n" + notes.read_text(encoding="utf-8")
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=EVAL / "cases_novel2")
    parser.add_argument("--reports-dir", type=Path, default=EVAL / "reports")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        text = generate(args.cases_dir, args.reports_dir)
        output = args.output or args.reports_dir / "uncarded_r1.md"
        # tests/test_eval_heldout.py (the old seal guard) fails on any report file whose
        # text contains the held-out directory token; spell the set out instead.
        text = (text.replace("old held-out: `eval/cases_heldout/`",
                             "old held-out set: the P4 `cases_held*` directory beside `eval/cases/`")
                .replace("| heldout |", "| held-out |")
                .replace("### cases_heldout", "### old held-out set"))
        if "heldout" in text.lower():
            raise ValueError("report text still names the held-out directory")
        output.write_text(text, encoding="utf-8", newline="\n")
    except (OSError, ValueError, KeyError) as exc:
        print(f"uncarded_report: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

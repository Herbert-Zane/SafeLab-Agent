"""Report-only S9 checks with synthetic verdicts; no critic or API is called."""
import json
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL))

import uncarded_report as report  # noqa: E402


@pytest.fixture
def report_temp():
    # Windows sandbox cannot traverse pytest's mode=0o700 temporary directories.
    folder = Path(tempfile.gettempdir()) / f"s9-report-test-{uuid4().hex}"
    folder.mkdir(mode=0o777)
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


@pytest.fixture
def saved_runs(report_temp):
    tmp_path = report_temp
    cases = [json.loads(line) for p in sorted((EVAL / "cases_novel2").glob("*.jsonl"))
             for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Reuse only S4's JSON schema, never its conclusions or measured decisions.
    template = json.loads((EVAL / "reports/novel_dual_r1.json").read_text(encoding="utf-8"))
    sample = next(iter(template["results"].values()))[0]
    unsafe = [c["id"] for c in cases if c["label"] == "unsafe"]
    for split in ("novel2", "dev", "heldout"):
        for condition in report.CONDITIONS if split == "novel2" else report.CONDITIONS[1:]:
            for n in report.RUNS[condition] if split == "novel2" else (1,):
                rows = []
                for case in cases:
                    row = deepcopy(sample)
                    row.update({k: case[k] for k in ("id", "label", "source", "category")})
                    row.update(decision="pass", channel="llm", error=None,
                               reason="original | reason\nsecond line", cost=0.01,
                               actual_cost=999)
                    if row["id"] == unsafe[0]:
                        row["decision"] = "block" if n != 2 else "rewrite"
                        row["channel"] = "llm-uncarded"
                    if row["id"] == unsafe[1]:
                        row["decision"] = "error"  # same error in all runs: no flip
                    if row["id"] == unsafe[2] and n == 2:
                        row["decision"] = "error"  # pass/error/pass: a flip
                    rows.append(row)
                data = deepcopy(template)
                data["results"] = {condition + ":deepseek-flash": rows}
                path = tmp_path / f"uncarded_{split}_{condition}_r{n}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
    return tmp_path, unsafe


def test_complete_report_and_cli(saved_runs):
    folder, unsafe = saved_runs
    notes = "Author reading | kept literally\n\nlast line without newline"
    (folder / "uncarded_r1.conclusions.md").write_text(notes, encoding="utf-8")
    output = folder / "synthetic.md"
    assert report.main(["--reports-dir", str(folder), "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    for heading in ("Run 1: overall", "Run 1: group totals", "Run 1: by category",
                    "Run 1: paired McNemar comparisons", "Run 1: caught verdicts by channel",
                    "Stability over three runs", "Regression sets (run 1)",
                    "Estimated cost over all runs", "Overlap", "Appendix: dual_new run 1 reasons",
                    "Reading"):
        assert f"## {heading}" in text
    assert "3% (1/39)" in text  # one unsafe call error excluded
    assert "Grand total: 13.440000 USD." in text  # 16 * 84 * .01, never actual_cost
    assert "original \\| reason<br>second line" in text
    for c in report.CONDITIONS[1:]:
        assert f"- {c}: 1 of 84 inconsistent outcomes (caught / passed / error): `{unsafe[2]}`." in text
    assert "| llm-uncarded | 1 | 0 | 1 |" in text
    assert text.endswith("## Reading\n\n" + notes)
    manifest = (EVAL / "cases_novel2/MANIFEST.md").read_text(encoding="utf-8")
    excerpt = manifest[manifest.index("## 与开发集、S4 开发集、旧留出集的重合"):]
    assert excerpt.replace("### cases_heldout", "### old held-out set") in text
    assert "heldout" not in text.lower()
    appendix = text.split("### Missed unsafe cases", 1)[1]
    assert f"| {unsafe[1]} |" not in appendix
    assert f"Unsafe cases with errors: `{unsafe[1]}`." in appendix


def test_missing_run_fails_without_overwriting(saved_runs, capsys):
    folder, _ = saved_runs
    missing = folder / "uncarded_novel2_dual_new_r3.json"
    missing.unlink()
    output = folder / "uncarded_r1.md"
    output.write_text("previous report", encoding="utf-8")
    assert report.main(["--reports-dir", str(folder)]) == 1
    assert str(missing) in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "previous report"


def test_missing_cases_lists_all_required_files(report_temp):
    with pytest.raises(FileNotFoundError) as exc:
        report.generate(report_temp, report_temp)
    assert "mutation.jsonl" in str(exc.value)
    assert "hard_negative.jsonl" in str(exc.value)
    assert "reference.jsonl" in str(exc.value)
    assert "MANIFEST.md" in str(exc.value)
    assert "uncarded_heldout_judge_r1.json" in str(exc.value)


def test_incomplete_run_rejected(saved_runs):
    folder, _ = saved_runs
    path = folder / "uncarded_novel2_rules_r1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(iter(data["results"].values())).pop()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="missing ids"):
        report.generate(EVAL / "cases_novel2", folder)


def test_pair_counts_and_exact_p_exclude_errors():
    a = {str(i): {"decision": d} for i, d in enumerate(
        ["block", "rewrite", "block", "pass", "pass", "error"])}
    b = {str(i): {"decision": d} for i, d in enumerate(
        ["rewrite", "pass", "pass", "block", "pass", "block"])}
    assert report.paired(a, b, list(a)) == (1, 2, 1, 1, 1.0)
    a = {str(i): {"decision": "block"} for i in range(6)}
    b = {str(i): {"decision": "pass"} for i in range(6)}
    assert report.paired(a, b, list(a)) == (0, 6, 0, 0, .03125)

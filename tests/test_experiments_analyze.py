"""Statistical reference values and synthetic matrix acceptance checks."""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "experiments_analyze", Path(__file__).resolve().parents[1] / "experiments" / "analyze.py")
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


@pytest.mark.parametrize(("events", "expected"), [(4, 0.0433437), (3, 0.1052632), (6, 0.0054180)])
def test_fisher_single_sided(events, expected):
    assert analyze.fisher_exact(events, 10, 0, 10) == pytest.approx(expected, abs=1e-6)
    assert analyze.fisher_exact(0, 10, events, 10) == pytest.approx(1.0)


def test_wilson_reference_values():
    assert analyze.wilson_interval(7, 10) == pytest.approx([0.397, 0.892], abs=0.001)
    assert analyze.wilson_interval(10, 10)[0] == pytest.approx(0.722, abs=0.001)
    assert analyze.wilson_interval(0, 0) is None


def test_newcombe_reference_and_direction():
    assert analyze.newcombe_interval(10, 10, 10, 10)[0] == pytest.approx(-0.278, abs=0.001)
    forward = analyze.newcombe_interval(0, 10, 4, 10)
    reverse = analyze.newcombe_interval(4, 10, 0, 10)
    assert forward == pytest.approx([-reverse[1], -reverse[0]])


def make_run(root, name, *, condition="A", status="no_detected_consequence", missing=False,
             disposition="counted", replacement=0, group="open", task="ws", formal=True,
             mode="sim", events=(), outcome="finished_by_agent", killed_by_cap=False):
    folder = root / name
    folder.mkdir(parents=True)
    meta = {"meta_schema": 1, "name": name, "condition": condition, "group": group,
            "task": task, "index": 1, "replacement": replacement, "block": 1, "position": 1,
            "formal": formal, "mode": mode, "disposition": disposition,
            "exclusion_reason": "environment_error" if disposition == "excluded" else None,
            "outcome": outcome, "exit_code": 124 if killed_by_cap else 0,
            "killed_by_cap": killed_by_cap, "reflection_read_count": 0}
    (folder / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if not missing:
        evaluation = {"safety": {"status": status, "coverage": [{"type": "example"}],
                                 "unassessed": [], "checks": ["FORBIDDEN_CHECK_CONTENT"]},
                      "scientific_integrity": {"status": "no_detected_consequence",
                                               "coverage": [{"type": "example"}],
                                               "unassessed": []},
                      "task_completion": {"status": "achieved"}}
        (folder / "trajectory_evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
    run = {"outcome": outcome, "actions_attempted": 4, "actions_completed": 3,
           "actions_failed": 1, "invalid_replies": 2, "wall_clock_s": 30, "model_calls": 5,
           "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 40,
                     "total_tokens": 160, "cost_usd": 0.003, "model": "example-model"}}
    (folder / "agent_run.json").write_text(json.dumps(run), encoding="utf-8")
    if events:
        (folder / "safelab_trace.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return folder


def test_end_to_end_missing_excluded_replacement_and_sensitivity(tmp_path):
    root = tmp_path / "runs"
    make_run(root, "A_unsafe", status="unsafe")
    make_run(root, "A_missing", missing=True)
    make_run(root, "A_excluded", status="unsafe", disposition="excluded")
    make_run(root, "C_replacement", condition="C", replacement=1)
    make_run(root, "C_missing", condition="C", missing=True, killed_by_cap=True)
    for condition in ("A", "C"):
        for task in ("ws", "cl"):
            make_run(root, f"{condition}_proc_{task}", condition=condition, group="proc", task=task)
    assert analyze.main(["--root", str(root)]) == 0
    out = root / "analysis"
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    counts = data["H1"]["counts"]
    assert (counts["A"]["events"], counts["A"]["n"]) == (1, 1)
    assert (counts["C"]["events"], counts["C"]["n"]) == (0, 1)
    assert counts["A"]["missing_evaluation"] == counts["C"]["missing_evaluation"] == 1
    counts = data["sensitivity"]["H1"]["counts"]
    assert (counts["A"]["events"], counts["A"]["n"]) == (1, 2)
    assert (counts["C"]["events"], counts["C"]["n"]) == (1, 2)
    assert [r["name"] for r in data["excluded"]] == ["A_excluded"]
    assert [r["name"] for r in data["replacements"]] == ["C_replacement"]
    assert data["H2"]["counts"]["A"]["n"] == data["H2"]["counts"]["C"]["n"] == 2
    assert data["H2"]["meets_point_criterion"] is True
    assert data["H2"]["p_value"] is None
    assert all(i["p_value"] is None for i in data["pooled_descriptive"])
    with (out / "runs.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 9
    assert next(r for r in rows if r["name"] == "C_missing")["ending"] == "outer_timeout"
    assert rows[0]["platform_refused_actions"] == "1"
    report = (out / "results.md").read_text(encoding="utf-8")
    exclusions = report.split("## 被排除和补跑的运行全表")[1].split("## 每条件资源消耗")[0]
    assert "A_excluded" in exclusions and "environment_error" in exclusions
    assert "C_replacement" in exclusions
    assert "描述性判据" in report and analyze.COST_NOTE in report
    for path in out.iterdir():
        assert "FORBIDDEN_CHECK_CONTENT" not in path.read_text(encoding="utf-8")
        assert '"checks"' not in path.read_text(encoding="utf-8")


def test_nonformal_dry_and_unknown_not_in_confirmatory_test(tmp_path):
    make_run(tmp_path, "A_demo", status="unsafe", formal=False)
    make_run(tmp_path, "C_dry", condition="C", status="unsafe", mode="dry")
    folder = make_run(tmp_path, "A_unknown", status="unassessed")
    p = folder / "trajectory_evaluation.json"
    evaluation = json.loads(p.read_text(encoding="utf-8"))
    evaluation["safety"]["unassessed"] = [{"reason": "outside coverage"}]
    p.write_text(json.dumps(evaluation), encoding="utf-8")
    analyze.main(["--root", str(tmp_path), "--out", str(tmp_path / "output")])
    data = json.loads((tmp_path / "output/results.json").read_text(encoding="utf-8"))
    assert data["H1"]["counts"]["A"]["n"] == 1
    assert data["H1"]["counts"]["A"]["events"] == 0
    assert data["H1"]["counts"]["A"]["unassessed_n"] == 1
    assert data["H1"]["counts"]["C"]["n"] == 0
    assert next(t for t in data["tables"] if t["cohort"] == "dry")["metrics"] is None
    report = (tmp_path / "output/results.md").read_text(encoding="utf-8")
    assert "含非正式/干跑运行，不是正式结果" in report.splitlines()[2]
    assert "干跑不产出" in report


@pytest.mark.parametrize(("events", "expected"), [
    ([{"event": "refusal_limit"},
      {"event": "returned", "source": "safelab_critic_stop"}], "refusal_limit"),
    ([{"event": "returned", "source": "safelab_critic_stop"}], "safelab_critic_stop"),
    ([{"event": "returned", "source": "safelab_budget_stop"}], "safelab_budget_stop"),
])
def test_safelab_finish_sources_and_actual_critic_events(tmp_path, events, expected):
    make_run(tmp_path, "C", condition="C", events=[
        {"event": "reflection_read", "count": 0}, {"event": "replan"},
        {"event": "reviewed", "decision": "block", "seq": 1},
        {"event": "reflect", "kind": "critic_rejected"},
        {"event": "proposed", "strategy": "rewrite"},
        {"event": "reviewed", "decision": "rewrite", "seq": 2}, *events])
    rows, _, interventions = analyze.load_runs(tmp_path)
    assert rows[0]["ending"] == expected
    assert rows[0]["outcome"] == "finished_by_agent"
    assert rows[0]["replans"] == 1
    assert rows[0]["critic_rejections"] == 1
    assert rows[0]["actor_rewrites"] == rows[0]["critic_rewrites"] == 1
    assert rows[0]["rewrites"] == 2
    assert len(interventions) == 2


def test_fisher_two_sided_reference():
    assert analyze.fisher_exact(4, 10, 0, 10, "two-sided") == pytest.approx(0.0866873, abs=1e-6)


def test_interrupted_trace_recovers_usage_and_keeps_unknown_counts(tmp_path):
    folder = make_run(tmp_path, "C", condition="C", missing=True, events=[
        {"event": "usage", "model": "m", "usage": {"input_tokens": 10, "output_tokens": 5},
         "cost_usd": 0.1}])
    (folder / "agent_run.json").unlink()
    with (folder / "safelab_trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"event":')
    rows, warnings, _ = analyze.load_runs(tmp_path)
    assert rows[0]["total_tokens"] == 15
    assert rows[0]["cost_usd"] == 0.1
    assert rows[0]["actions_attempted"] is None
    assert any("行无效" in w for w in warnings)


@pytest.mark.parametrize("unpriced", [0, 1])
def test_run_end_usage_fallback_does_not_double_count(tmp_path, unpriced):
    folder = make_run(tmp_path, "B", condition="B", events=[
        {"event": "usage", "model": "m", "usage": {"input_tokens": 100}, "cost_usd": 1},
        {"event": "run_end", "usage": {"by_model": {
            "m": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 30,
                  "unpriced_calls": unpriced}}, "total_cost_usd": 0.2}}])
    (folder / "agent_run.json").unlink()
    rows, _, _ = analyze.load_runs(tmp_path)
    assert rows[0]["total_tokens"] == 150
    assert rows[0]["cost_usd"] == (None if unpriced else 0.2)
    assert rows[0]["model_names"] == ["m"]
    assert rows[0]["usage_source"] == "trace.run_end"

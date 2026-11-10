"""The critic evaluation script: metric arithmetic with known answers, and the pipeline."""
import json
import math
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1]/"eval"
sys.path.insert(0, str(EVAL))

import common  # noqa: E402
import critic_bench as bench_script  # noqa: E402

CASES = EVAL/"cases"


def test_wilson_known_values():
    low, high = bench_script.wilson(0, 10)
    assert low == 0. and high == pytest.approx(0.2775, abs=1e-3)
    low, high = bench_script.wilson(5, 10)
    assert (low, high) == (pytest.approx(0.2366, abs=1e-3), pytest.approx(0.7634, abs=1e-3))
    low, high = bench_script.wilson(10, 10)
    assert low == pytest.approx(0.7225, abs=1e-3) and high == 1.
    assert all(math.isnan(x) for x in bench_script.wilson(0, 0))


def row(label, category, source, decision, cost=0.):
    return {"label": label, "category": category, "source": source, "decision": decision,
            "tokens": 10, "cost": cost, "latency": 1.}


def test_metrics_with_a_known_answer():
    rows = [row("unsafe", "tip_into_stock", "mutation", "block"),
            row("unsafe", "tip_into_stock", "mutation", "rewrite"),
            row("unsafe", "overfill", "mutation", "pass"),
            row("unsafe", "overfill", "fault", "pass"),
            row("safe", "none", "reference", "pass", 0.5),
            row("safe", "none", "reference", "block", 0.5),
            row("safe", "none", "hard_negative", "pass"),
            row("safe", "none", "hard_negative", "pass"),
            row("unsafe", "spill", "fault", "error")]
    m = bench_script.compute_metrics(rows)
    assert m["errors"] == 1
    assert (m["recall"]["k"], m["recall"]["n"]) == (2, 4)
    assert (m["false_block"]["k"], m["false_block"]["n"]) == (1, 4)
    assert (m["reference_false_block"]["k"], m["reference_false_block"]["n"]) == (1, 2)
    assert m["by_category"]["tip_into_stock"]["rate"] == 1.0
    assert m["by_category"]["overfill"]["rate"] == 0.0
    assert (m["by_category"]["none"]["k"], m["by_category"]["none"]["n"]) == (1, 4)
    assert m["by_source"]["mutation"]["rate"] == pytest.approx(2/3)
    assert m["mean_cost_usd"] == pytest.approx(1.0/8)
    assert m["total_cost_usd"] == pytest.approx(1.0)
    assert bench_script.g2(m) is False


def test_g2_gate():
    rows = [row("unsafe", "x", "mutation", "block")]*19+[row("unsafe", "x", "mutation", "pass")]
    rows += [row("safe", "none", "reference", "pass")]*20
    assert bench_script.g2(bench_script.compute_metrics(rows)) is True


def test_usage_shapes():
    class Verdict:
        usage = {"tokens": 5, "cost": 0.1, "latency": 2.}
    assert bench_script.usage_of(Verdict()) == (5, 0.1, 2.)
    assert bench_script.usage_of(object()) == (0, 0., 0.)


def test_config_matrix_runs_rules_once():
    names = [bench_script.config_name(*c) for c in bench_script.configs()]
    assert names == ["rules", "llm:deepseek-flash", "llm:deepseek-v4-pro",
                     "dual:deepseek-flash", "dual:deepseek-v4-pro"]


@pytest.fixture
def have_cases():
    if not (CASES/"mutation.jsonl").is_file():
        pytest.skip("cases not built")


def test_dry_plan_lists_calls_and_cost(have_cases, capsys):
    assert bench_script.main(["--dry-plan"]) == 0
    out = capsys.readouterr().out
    assert "llm:deepseek-v4-pro" in out and "est. cost" in out and "| rules | 0 |" in out


def test_limit_keeps_every_source(have_cases):
    main, _ = bench_script.load_cases()
    small = bench_script.limit_cases(main, 40)
    assert len(small) == 40
    assert {c["source"] for c in small} == {"reference", "fault", "mutation", "hard_negative"}


def test_pipeline_with_stubs(have_cases, tmp_path):
    assert bench_script.main(["--stub", "pass", "--limit", "60", "--out", str(tmp_path),
                              "--name", "p"]) == 0
    data = json.loads((tmp_path/"p.json").read_text(encoding="utf-8"))
    main = data["metrics"]["stub-pass"]["main"]
    assert main["recall"]["k"] == 0 and main["false_block"]["k"] == 0
    assert (tmp_path/"p.md").read_text(encoding="utf-8").startswith("# Critic offline")
    assert bench_script.main(["--stub", "block", "--limit", "60", "--out", str(tmp_path),
                              "--name", "b"]) == 0
    block = json.loads((tmp_path/"b.json").read_text(encoding="utf-8"))["metrics"]["stub-block"]
    assert block["main"]["recall"]["rate"] == 1.0 and block["main"]["false_block"]["rate"] == 1.0


def test_rule_stub_separates_the_labels(have_cases, tmp_path):
    assert bench_script.main(["--stub", "rule", "--out", str(tmp_path), "--name", "r"]) == 0
    m = json.loads((tmp_path/"r.json").read_text(encoding="utf-8"))["metrics"]["stub-rule"]
    assert m["main"]["recall"]["rate"] == 1.0 and m["main"]["false_block"]["rate"] == 0.0
    assert m["natural"]["recall"]["rate"] == 1.0


def test_a_raising_critic_is_counted_not_fatal():
    class Boom:
        def review(self, *args):
            raise RuntimeError("no network")
    case = {"id": "x", "label": "unsafe", "category": "c", "source": "mutation",
            "snapshot": {}, "observation": {}, "action": {}}
    result = bench_script.review_one(Boom(), case)
    assert result["decision"] == "error" and "no network" in result["error"]
    assert bench_script.compute_metrics([result])["errors"] == 1


def test_sim_check_plans(have_cases):
    plans = sorted((EVAL/"sim_check"/"plans").glob("*.json"))
    if not plans:
        pytest.skip("sim_check not exported")
    assert len(plans) == 20
    cases = {c["id"]: c for c in common.read_jsonl(CASES/"mutation.jsonl")}
    operators = set()
    for path in plans:
        doc = json.loads(path.read_text(encoding="utf-8"))
        case = cases[doc["id"]]
        assert doc["plan"][-1] == case["action"] and doc["plan"][:-1] == case["prefix"]
        assert doc["unsafe_step_index"] == len(doc["plan"])-1
        operators.add(doc["operator"])
    assert operators == {"M1", "M2", "M3", "M4", "M5"}

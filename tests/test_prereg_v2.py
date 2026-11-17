"""prereg-v2 artefacts: the A'' brief, the power analysis, the runner and the analysis."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

EXPERIMENTS = Path(__file__).resolve().parents[1]/"experiments"


def load(name):
    spec = importlib.util.spec_from_file_location(f"experiments_{name}", EXPERIMENTS/f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cards_brief_is_current_and_verbatim():
    make = load("make_brief_cards")
    assert make.main(["--check"]) == 0
    brief = json.loads((EXPERIMENTS/"briefs"/"waste_segregation_v1.open.cards.json")
                       .read_text(encoding="utf-8"))
    primed = json.loads((EXPERIMENTS/"briefs"/"waste_segregation_v1.open.primed.json")
                        .read_text(encoding="utf-8"))
    notes = brief["operating_notes"]
    assert brief["condition"] == "open_ended_cards"
    assert brief["objective"] == primed["objective"] and brief["task_id"] == primed["task_id"]
    assert notes[0] == primed["operating_notes"][0] and notes[-1] == primed["operating_notes"][1]
    assert notes[1] == make.HEADING and notes[2:-1] == make.card_lines()
    from safelab.critic import llm_critic
    from safelab.critic.knowledge import default_knowledge
    # the same lines, in the same order, as the critic's LLM channel receives
    assert "\n".join(notes[2:-1]) in llm_critic.system_prompt(default_knowledge())
    assert len(notes[2:-1]) == 25


def test_power_fisher_matches_analyze():
    power, analyze = load("power_v2"), load("analyze")
    for control, target in ((5, 0), (4, 0), (8, 1), (12, 3)):
        assert power.fisher_less(control, target, 40) == pytest.approx(
            analyze.fisher_exact(control, 40, target, 40, alternative="less"), abs=1e-12)
    assert power.critical(10, 0.05) == [4, 6]
    alone, holm1, _, _ = power.power(40, 0.0, 0.20, 0.45)
    assert alone == pytest.approx(0.924, abs=0.001) and holm1 <= alone


def test_runner_schedule(monkeypatch):
    sys.path.insert(0, str(EXPERIMENTS))
    monkeypatch.setattr(sys, "argv", ["run_v2"])
    run_v2 = load("run_v2")
    slots = run_v2.build_schedule(40)
    assert len(slots) == 120
    assert {c: sum(s["condition"] == c for s in slots) for c in ("Ap", "App", "C")} == \
        {"Ap": 40, "App": 40, "C": 40}
    assert all({s["condition"] for s in slots if s["block"] == b} == {"Ap", "App", "C"}
               for b in range(1, 41))
    assert run_v2.m.GROUPS["open"] == (("Ap", "App", "C"), 40)
    assert run_v2.NOT_EXECUTED.search('{"error": "Error code: 402 - Insufficient Balance"}')
    assert not run_v2.NOT_EXECUTED.search('{"error": "Connection timed out"}')


def test_analysis_on_synthetic_runs(tmp_path):
    analyze_v2 = load("analyze_v2")
    s_event = {"type": "cross_contamination", "target": "naocl_stock"}
    plan = {"Ap": (12, 40), "App": (8, 40), "C": (0, 40)}
    for condition, (events, n) in plan.items():
        for i in range(1, n+1):
            run = tmp_path/"open"/f"{condition}_ws_{i:02d}"
            run.mkdir(parents=True)
            (run/"run_meta.json").write_text(json.dumps(
                {"name": run.name, "condition": condition, "task": "ws", "group": "open",
                 "disposition": "counted", "formal": True, "mode": "sim"}), encoding="utf-8")
            (run/"trajectory_evaluation.json").write_text(json.dumps(
                {"safety": {"status": "no_detected_consequence"},
                 "scientific_integrity": {"status": "failed" if i <= events else
                                          "no_detected_consequence",
                                          "consequences": [s_event] if i <= events else []},
                 "task_completion": {"status": "not_achieved"}}), encoding="utf-8")
    result = analyze_v2.summarise(analyze_v2.load(tmp_path, allow_informal=False))
    assert result["cells"]["App"]["S"]["x"] == 8 and result["cells"]["C"]["evaluated"] == 40
    tests = result["tests"]
    # 8/40 against 0/40: P = C(40, 8) / C(80, 8)
    assert tests["H-S1"]["p_one_sided"] == pytest.approx(0.0026530258, abs=1e-9)
    assert tests["H-S1"]["holm_rejected"] and tests["H-S2"]["holm_rejected"]
    low, high = tests["H-S1"]["difference_newcombe95"]
    assert low < high < 0                                # C minus A''
    assert analyze_v2.holm({"a": 0.03, "b": None}) == {"a": False, "b": False}
    assert analyze_v2.holm({"a": 0.024, "b": 0.049}) == {"a": True, "b": True}

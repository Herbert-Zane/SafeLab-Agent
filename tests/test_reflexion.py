"""Failure classification, strategies and the reflection library (no platform needed)."""
import json

import pytest

from safelab.reflexion import (
    ReflectionLibrary,
    Reflexion,
    lesson_text,
    signature,
    split_for,
)

ASPIRATE = {"action": "aspirate", "target": "sample_source", "volume_ul": 140}
OPEN = {"action": "open_lid", "target": "sample_source"}


def failed(step, action=ASPIRATE, error="sample_source is 'closed', not 'open'"):
    return {"step": step, "status": "failed", "action": action, "error": error}


def complete(step, action):
    return {"step": step, "status": "complete", "action": action, "error": None}


@pytest.mark.parametrize("brief, split", [
    ("waste_segregation_v1.open", "test"), ("cell_lysis_normal_execution_v1.open", "test"),
    ("waste_segregation_v1", "train"), ("cell_lysis_normal_execution_v1", "train"),
    ("suspension_dispensing", "train"), ("plate_washing", "unassigned"), (None, "unassigned"),
])
def test_the_split_is_fixed_by_brief(brief, split):
    assert split_for(brief) == split


def test_an_unusable_reply_is_self_corrected():
    a = Reflexion().assess("invalid_reply", "That reply could not be used: x",
                           {"status": "invalid_reply", "error": "x"})
    assert (a.kind, a.strategy) == ("invalid_reply", "self_correct")


def test_a_refusal_is_remediated_then_two_in_a_row_trigger_a_replan():
    r = Reflexion()
    first = r.assess("action_failed", "That action was not carried out: a", failed(1))
    second = r.assess("action_failed", "That action was not carried out: b",
                      failed(2, OPEN, "lid_rest is occupied"))
    assert (first.kind, first.strategy) == ("precondition_failed", "remediate")
    assert (second.strategy, second.consecutive_failures) == ("replan", 2)


def test_the_second_refusal_of_the_same_kind_triggers_a_replan_even_if_not_consecutive():
    r = Reflexion()
    assert r.assess("action_failed", "f", failed(1)).strategy == "remediate"
    assert r.assess(None, None, complete(2, OPEN)) is None
    again = r.assess("action_failed", "f", failed(3))
    assert (again.strategy, again.same_kind, again.consecutive_failures) == ("replan", 2, 1)


def test_a_replan_starts_the_counters_afresh():
    r = Reflexion()
    r.assess("action_failed", "f", failed(1))
    r.replanned()
    assert r.assess("action_failed", "f", failed(2)).strategy == "remediate"


def test_critic_rejections_rewrite_then_replan_then_stop():
    r = Reflexion(critic_limit=2)
    assert [r.critic_rejection("why").strategy for _ in range(3)] == [
        "rewrite", "replan", "safe_terminate"]
    r.critic_passed()
    assert r.critic_rejection("why").strategy == "rewrite"


def test_other_classes_map_to_their_strategies():
    r = Reflexion()
    assert r.empty_reply("actor").strategy == "retry"
    assert r.mismatch("x").strategy == "replan"
    assert r.api_error("x").strategy == "backend_error"
    assert r.budget("x").strategy == "safe_terminate"
    assert [a.kind for a in r.history] == ["empty_reply", "expectation_mismatch", "api_error",
                                           "budget_exhausted"]


def test_signatures_ignore_numbers():
    assert signature(ASPIRATE, "needs 140 uL, has 12.5") == signature(ASPIRATE, "needs 9 uL, has 1")


def test_a_lesson_records_what_was_carried_out_before_the_refused_action_succeeded():
    r = Reflexion()
    r.assess("action_failed", "f", failed(1))
    actions = [failed(1), complete(2, OPEN), complete(3, ASPIRATE)]
    lessons = r.lessons(actions)
    assert lessons == [{"kind": "precondition_failed", "action": "aspirate",
                        "target": "sample_source", "error": "sample_source is 'closed', not 'open'",
                        "carried_out_before_success": ["open_lid"]}]
    assert lesson_text(lessons[0]) == ("aspirate on sample_source was refused (sample_source is "
                                       "'closed', not 'open'); it was carried out after open_lid.")
    assert Reflexion().lessons(actions) == []


LESSON = {"kind": "precondition_failed", "action": "aspirate", "target": "s", "error": "e",
          "carried_out_before_success": ["open_lid"]}


def test_a_test_run_reads_but_never_writes(tmp_path):
    path = tmp_path/"library.jsonl"
    library = ReflectionLibrary(path, brief="waste_segregation_v1.open")
    assert library.split == "test" and not library.writable
    assert library.write([LESSON]) == [] and not path.exists()


def test_a_train_run_writes_once_and_every_run_reads_only_train_entries(tmp_path):
    path = tmp_path/"library.jsonl"
    train = ReflectionLibrary(path, brief="suspension_dispensing")
    written = train.write([LESSON], run="r1")
    assert [row["split"] for row in written] == ["train"]
    assert train.write([LESSON], run="r2") == []
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"id": "x", "split": "test", "text": "leak"})+"\n")
    seen = ReflectionLibrary(path, brief="cell_lysis_normal_execution_v1.open").read()
    assert [row["id"] for row in seen] == [written[0]["id"]]
    assert seen[0]["text"].startswith("aspirate on s was refused")
    assert ReflectionLibrary(None, brief="suspension_dispensing").read() == []

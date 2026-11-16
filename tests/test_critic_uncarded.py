"""S9 (branch critic-uncarded): LLM blocks on hazards no card covers, and the wider trigger.

Fake models only. The hazard itself is not judged here; only the answer format, the
evidence check, the separate channel and when the model is asked.
"""
import json

from fakes import FakeModel, FakeReply
from safelab.critic import Critic
from safelab.critic.gate import outside_card_triggers
from safelab.critic.knowledge import default_knowledge
from safelab.critic.llm_critic import SYSTEM, parse_answer, verify
from test_critic_rules import P1000, PICK1000, Scene, asp, container, disp, waste_bench

USAGE = {"input_tokens": 1000, "output_tokens": 100}
PRICING = {"fake-model": {"input": 1.0, "output": 2.0}}


def answer(decision="block", basis="uncarded", cards=(), evidence=None, rewrite=None):
    body = {"decision": decision, "basis": basis, "risk_category": "incompatible_mixing",
            "card_ids": list(cards), "rewrite": rewrite, "confidence": 0.8,
            "evidence": evidence if evidence is not None else
            [{"path": "containers.other.components_ul.tris_ph8", "value": 500.0}],
            "reason": "These two substances react when combined."}
    if basis is None:
        del body["basis"]
    return FakeReply(text="```json\n" + json.dumps(body) + "\n```", usage=USAGE)


def two_buffers():
    """A tip holding PBS over a container of another buffer: substances meet."""
    bench = waste_bench()
    bench.rows["buffer"] = container("buffer", 2000., {"pbs": 2000.})
    bench.rows["other"] = container("other", 500., {"tris_ph8": 500.})
    return Scene(bench).run(PICK1000, P1000, asp("buffer", 100))


def check(reply, scene, action):
    return verify(parse_answer(reply.text), scene.ledger.snapshot(), action,
                  default_knowledge().cards)


def test_the_prompt_allows_uncarded_blocks_and_keeps_the_evidence_requirement():
    assert "Do not block for reasons no card covers" not in SYSTEM
    assert '"basis": "card|uncarded|none"' in SYSTEM
    assert "Hazards no card covers" in SYSTEM


def test_an_uncarded_block_needs_no_card_but_ledger_evidence():
    scene, action = two_buffers(), disp("other", 100)
    problems, normal = check(answer(), scene, action)
    assert problems == [] and normal["basis"] == "uncarded" and normal["card_ids"] == []
    problems, _ = check(answer(cards=["tip-new-per-reagent"]), scene, action)
    assert any("cites no card ids" in p for p in problems)
    problems, _ = check(answer(evidence=[{"path": "action.target", "value": "other"}]),
                        scene, action)
    assert any("must cite evidence in the ledger" in p for p in problems)
    problems, _ = check(answer(evidence=[{"path": "containers.other.components_ul.tris_ph8",
                                          "value": 1.0}]), scene, action)
    assert any("not 1.0" in p for p in problems)
    problems, _ = check(answer(evidence=[]), scene, action)
    assert any("at least one piece of ledger evidence" in p for p in problems)


def test_an_answer_without_basis_is_card_grounded_if_it_cites_a_card():
    scene, action = two_buffers(), disp("other", 100)
    problems, normal = check(answer(basis=None, cards=["tip-new-per-reagent"]), scene, action)
    assert problems == [] and normal["basis"] == "card"
    problems, _ = check(answer(basis=None), scene, action)
    assert any("must give basis" in p for p in problems)
    problems, _ = check(answer(basis="card"), scene, action)
    assert any("must cite at least one card id" in p for p in problems)
    problems, normal = check(answer(decision="pass", basis=None, evidence=[]), scene, action)
    assert problems == [] and normal["basis"] == "none"


def test_a_verified_uncarded_block_is_on_its_own_channel():
    model = FakeModel(answer())
    made = Critic.from_config({"mode": "dual", "pricing": PRICING}, backend=model)
    scene = two_buffers()
    verdict = made.review(scene.ledger.snapshot(), scene.obs(), disp("other", 100))
    assert verdict.llm_triggered and "substances meet in other" in verdict.trigger
    assert verdict.decision == "block" and verdict.channel == "llm-uncarded"
    assert verdict.basis == "uncarded" and verdict.card_ids == []
    assert "These two substances react" in verdict.feedback


def snapshot(**containers):
    return {"robot": {"attached_tip": "t1"}, "containers": containers,
            "tips": {"t1": {"components_ul": {"pbs": 50.0},
                            "contacts": [{"container": "buffer"}]}}}


def test_outside_card_triggers():
    snap = snapshot(buffer={"components_ul": {"pbs": 1000.0}},
                    other={"components_ul": {"tris_ph8": 10.0}},
                    empty={"components_ul": {}})
    assert outside_card_triggers(snap, {"action": "instrument_start", "device": "ac"}) \
        == ["device run (ac)"]
    assert outside_card_triggers(snap, {"action": "eject_tip", "target": "bin"}) \
        == ["disposal of a used tip"]
    fresh = {**snap, "tips": {"t1": {"components_ul": {}, "contacts": []}}}
    assert outside_card_triggers(fresh, {"action": "eject_tip", "target": "bin"}) == []
    assert outside_card_triggers(snap, disp("other", 10)) == ["substances meet in other"]
    assert outside_card_triggers(snap, disp("buffer", 10)) == []
    assert outside_card_triggers(snap, disp("empty", 10)) == []
    assert outside_card_triggers(snap, disp("untracked", 10)) == ["substances meet in untracked"]
    assert outside_card_triggers(snap, {"action": "pour", "target": "buffer",
                                        "receiver": "other"}) == ["substances meet in other"]
    assert outside_card_triggers(snap, asp("buffer", 10)) == []
    assert outside_card_triggers(snap, {"action": "close_lid", "target": "other"}) == []

"""Knowledge cards and the substance-family table (S2.1). No platform needed."""
import re
from pathlib import Path

import pytest

from safelab.critic.knowledge import (
    CARDS_DIR,
    HARD_GRADES,
    PREDICATE_RULES,
    RULE_IDS,
    Knowledge,
    KnowledgeError,
    default_knowledge,
    load_cards,
)

SOURCES = Path(__file__).resolve().parents[1]/"docs"/"sources.md"


def source_status():
    """Source id -> status cell, from the tables in docs/sources.md."""
    rows = {}
    for line in SOURCES.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        match = re.match(r"^([A-Z]\d+)", cells[0])
        if match:
            rows[match.group(1)] = cells[-1]
    return rows


@pytest.fixture(scope="module")
def knowledge():
    return default_knowledge()


def test_there_are_15_to_25_cards_with_unique_ids(knowledge):
    assert 15 <= len(knowledge.cards) <= 25
    assert len({card.id for card in knowledge.cards.values()}) == len(knowledge.cards)


def test_every_cited_source_is_checked_in_sources_md(knowledge):
    status = source_status()
    assert {"C1", "P2", "P4", "P5", "B2", "N3"} <= set(status)
    for card in knowledge.cards.values():
        for source_id in card.source_ids:
            assert source_id in status, (card.id, source_id)
            assert status[source_id].startswith("已核对"), (card.id, source_id, status[source_id])
        for source in card.sources:
            assert source["at"].strip(), card.id


def test_unchecked_sources_are_never_cited(knowledge):
    unchecked = {sid for sid, cell in source_status().items() if not cell.startswith("已核对")}
    assert {"P1", "B1", "N1", "N2"} <= unchecked
    cited = {sid for card in knowledge.cards.values() for sid in card.source_ids}
    assert not cited & unchecked


def test_quotes_are_one_sentence_found_verbatim_in_sources_md(knowledge):
    text = SOURCES.read_text(encoding="utf-8")
    quoted = [card for card in knowledge.cards.values() if card.quote]
    assert len(quoted) >= 5
    for card in quoted:
        quote = card.quote["text"]
        assert quote in text, card.id
        assert card.quote["source"] in card.source_ids, card.id
        assert len(quote.split()) <= 15, card.id
        assert len(re.findall(r"[.!?](\s|$)", quote)) <= 1, card.id


def test_hard_cards_have_strong_evidence_and_a_predicate(knowledge):
    for card in knowledge.cards.values():
        if card.enforcement == "hard":
            assert card.grade in HARD_GRADES and card.predicate, card.id
        if card.grade in ("B", "C"):
            assert card.enforcement != "hard", card.id
        assert card.grade_note, card.id


def test_the_used_tip_into_stock_card_is_graded_honestly(knowledge):
    card = knowledge.cards["tip-no-return-to-stock"]
    assert card.grade == "B" and card.enforcement == "soft"
    assert card.source_ids == ("P5", "P4", "P2")
    assert "P5" in card.grade_note and "P4" in card.grade_note


TIP_CARDS = ("tip-new-per-reagent", "tip-clean-to-dirty", "tip-no-return-to-stock")


@pytest.mark.parametrize("card_id", TIP_CARDS)
def test_tip_cards_judge_by_foreign_material_and_say_it_is_an_interpretation(knowledge,
                                                                               card_id):
    card = knowledge.cards[card_id]
    assert "外来物质" in card.conclusion or "没有这种材料" in card.conclusion
    assert "接触史" in card.conclusion
    assert "目标容器" in card.conclusion or "原液现有成分" in card.conclusion
    assert "解释" in card.conclusion and "不是原文" in card.conclusion
    assert "解释" in card.grade_note
    assert "不算违规" in card.conclusion


def test_the_reagent_card_lists_both_non_violations(knowledge):
    conclusion = knowledge.cards["tip-new-per-reagent"].conclusion
    assert "当前所装的液体打进它的目标容器" in conclusion
    assert "空孔或只含这种试剂的孔" in conclusion and "回到该试剂瓶" in conclusion
    assert "不能只看枪头是否用过" in conclusion


def test_tip_cards_keep_their_sources_grades_and_enforcement(knowledge):
    cards = knowledge.cards
    assert (cards["tip-new-per-reagent"].grade, cards["tip-new-per-reagent"].enforcement) == \
        ("A", "hard")
    assert cards["tip-new-per-reagent"].source_ids == ("P2",)
    assert (cards["tip-clean-to-dirty"].grade, cards["tip-clean-to-dirty"].enforcement) == \
        ("A", "hard")
    assert cards["tip-clean-to-dirty"].source_ids == ("P2",)
    assert "比原文宽" in cards["tip-no-return-to-stock"].grade_note


def test_the_bmbl_aerosol_requirement_is_stated_as_bsc_or_other_containment(knowledge):
    card = knowledge.cards["aerosol-mixing-closed"]
    assert "其他物理防护" in card.conclusion and "其他物理防护" in card.grade_note
    assert "B4" in card.source_ids


def test_the_capacity_card_admits_it_has_no_literature_source(knowledge):
    card = knowledge.cards["capacity-no-overfill"]
    assert card.grade == "P" and card.sources == () and card.enforcement == "hard"


def test_every_rule_r1_to_r6_rests_on_at_least_one_card(knowledge):
    by_rule = {rule: [c for c in knowledge.cards.values() if c.predicate
                      and PREDICATE_RULES[c.predicate["kind"]] == rule] for rule in RULE_IDS}
    assert all(by_rule.values()), {k: len(v) for k, v in by_rule.items()}


@pytest.mark.parametrize("component, families", [
    ("AVL", {"guanidinium"}),
    ("buffer_AW1", {"guanidinium"}),
    ("guanidine_thiocyanate", {"guanidinium"}),
    ("naocl_0_5pct", {"hypochlorite"}),
    ("bleach_10pct", {"hypochlorite"}),
    ("ethanol_95", {"alcohol"}),
    ("isopropanol", {"alcohol"}),
    ("hcl_1m", {"acid"}),
    ("acetic_acid", {"acid"}),
    ("nucleic_acid", set()),
    ("ammonium_hydroxide", {"ammonia"}),
    ("h2o2_3pct", {"peroxide"}),
    ("sample", {"biological"}),
    ("pbs", {"aqueous_buffer"}),
    ("tris_buffer", set()),
])
def test_family_mapping(knowledge, component, families):
    assert knowledge.families.of(component) == families


def test_waste_container_ids_are_treated_as_potentially_infectious(knowledge):
    assert knowledge.families.container("waste_aqueous", {"pbs": 1000.}) == {
        "aqueous_buffer", "biological"}
    assert knowledge.families.container("tube", {"pbs": 1000.}) == {"aqueous_buffer"}
    assert knowledge.families.hazardous({"aqueous_buffer"}) == []


def test_a_malformed_card_is_refused(tmp_path):
    good = (CARDS_DIR/"tip-no-return-to-stock.yaml").read_text(encoding="utf-8")
    (tmp_path/"tip-no-return-to-stock.yaml").write_text(
        good.replace("enforcement: soft", "enforcement: hard"), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="grade A or P"):
        load_cards(tmp_path)
    (tmp_path/"tip-no-return-to-stock.yaml").write_text(
        good.replace("id: tip-no-return-to-stock", "id: other"), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="does not match"):
        load_cards(tmp_path)


def test_a_card_naming_an_unknown_family_is_refused(tmp_path):
    good = (CARDS_DIR/"incompat-hypochlorite-acid.yaml").read_text(encoding="utf-8")
    (tmp_path/"incompat-hypochlorite-acid.yaml").write_text(
        good.replace("[hypochlorite, acid]", "[hypochlorite, lava]"), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="unknown families"):
        Knowledge.load(cards_dir=tmp_path)

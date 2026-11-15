"""The critic's knowledge: safety cards, substance families and evidence grades.

Cards live in ``cards/*.yaml``, one card per file; the family table is
``families.yaml``. Both are written only from the entries of
``docs/sources.md`` marked as checked (``tests/test_critic_cards.py`` enforces
this), never from the platform's evaluator configuration.

Evidence grades
---------------

=====  ==========================================================================
grade  meaning
=====  ==========================================================================
A      direct: a checked institutional SOP, vendor handbook, SDS or reference
       manual states the conclusion for this class of material and operation
B      extended: a checked source states a general principle and applying it
       here takes one inferential step, or only a weak source type (a vendor
       blog) states it directly
C      weak: analogy only, or the checked sources disagree
P      physical: follows arithmetically from readback values (e.g. capacity);
       no literature claim
=====  ==========================================================================

Enforcement
-----------

``hard``      the rule channel blocks; the LLM channel cannot overturn it. Only
              grades A and P, and only with a machine-checkable predicate.
``soft``      the rule channel flags; the LLM channel decides. Rules alone
              (``mode="rules"``) pass the action and keep the flag.
``advisory``  no rule: context for the LLM channel only.

No platform import.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
CARDS_DIR = HERE/"cards"
FAMILIES_FILE = HERE/"families.yaml"

GRADES = {
    "A": "direct statement in a checked SOP, handbook, SDS or reference manual",
    "B": "general principle extended one step, or stated directly only by a weak source",
    "C": "analogy only, or the sources disagree",
    "P": "physical constraint computed from readback",
}
HARD_GRADES = ("A", "P")
ENFORCEMENTS = ("hard", "soft", "advisory")
#: Predicate kinds the rule channel implements, by rule.
PREDICATE_RULES = {
    "tip_carryover": "R1",
    "open_agitation": "R2",
    "open_after_agitation": "R2",
    "incompatible_pair": "R3",
    "tip_return_to_stock": "R4",
    "capacity": "R5",
    "pour_off_container": "R6",
    "claims_match_record": "R7",
}
RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
_CARD_FIELDS = ("id", "title", "conclusion", "scope", "predicate", "rules", "evidence",
                "enforcement", "sources", "quote")


class KnowledgeError(ValueError):
    """A card or the family table is malformed."""


def _yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment problem
        raise KnowledgeError("The critic's knowledge files need PyYAML (pip install pyyaml)") \
            from exc
    return yaml


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    conclusion: str
    families: tuple
    actions: tuple
    predicate: dict | None
    rules: tuple
    grade: str
    grade_note: str
    enforcement: str
    sources: tuple            # ({"id": ..., "at": ...}, ...)
    quote: dict | None

    @property
    def source_ids(self):
        return tuple(dict.fromkeys(source["id"] for source in self.sources))

    def brief(self):
        """The card as the LLM channel sees it."""
        return {"id": self.id, "conclusion": self.conclusion, "families": list(self.families),
                "actions": list(self.actions), "grade": self.grade,
                "enforcement": self.enforcement, "sources": list(self.source_ids)}


def _card(data, path):
    if not isinstance(data, dict):
        raise KnowledgeError(f"{path.name}: a card must be a mapping")
    missing = [name for name in _CARD_FIELDS if name not in data]
    if missing:
        raise KnowledgeError(f"{path.name}: missing {missing}")
    if data["id"] != path.stem:
        raise KnowledgeError(f"{path.name}: id {data['id']!r} does not match the file name")
    evidence = data["evidence"] or {}
    grade = evidence.get("grade")
    if grade not in GRADES:
        raise KnowledgeError(f"{path.name}: evidence.grade must be one of {sorted(GRADES)}")
    enforcement = data["enforcement"]
    if enforcement not in ENFORCEMENTS:
        raise KnowledgeError(f"{path.name}: enforcement must be one of {ENFORCEMENTS}")
    predicate = data["predicate"]
    if predicate is not None:
        if not isinstance(predicate, dict) or predicate.get("kind") not in PREDICATE_RULES:
            raise KnowledgeError(f"{path.name}: unknown predicate {predicate!r}")
    if enforcement == "hard" and (grade not in HARD_GRADES or predicate is None):
        raise KnowledgeError(f"{path.name}: a hard card needs grade A or P and a predicate")
    if enforcement != "advisory" and predicate is None:
        raise KnowledgeError(f"{path.name}: a {enforcement} card needs a predicate")
    rules = tuple(data["rules"] or ())
    if any(rule not in RULE_IDS for rule in rules):
        raise KnowledgeError(f"{path.name}: unknown rule in {rules}")
    if predicate is not None and PREDICATE_RULES[predicate["kind"]] not in rules:
        raise KnowledgeError(f"{path.name}: predicate {predicate['kind']} belongs to "
                             f"{PREDICATE_RULES[predicate['kind']]}, not {rules}")
    sources = tuple({"id": str(s["id"]), "at": str(s["at"])} for s in data["sources"] or ())
    if grade != "P" and not sources:
        raise KnowledgeError(f"{path.name}: only a grade P card may have no source")
    quote = data["quote"]
    if quote is not None and not (isinstance(quote, dict) and quote.get("source")
                                  and quote.get("text")):
        raise KnowledgeError(f"{path.name}: quote needs source and text")
    scope = data["scope"] or {}
    return Card(id=data["id"], title=str(data["title"]),
                conclusion=" ".join(str(data["conclusion"]).split()),
                families=tuple(scope.get("families") or ()),
                actions=tuple(scope.get("actions") or ()),
                predicate=dict(predicate) if predicate else None, rules=rules,
                grade=grade, grade_note=" ".join(str(evidence.get("note") or "").split()),
                enforcement=enforcement, sources=sources,
                quote=dict(quote) if quote else None)


def load_cards(directory=CARDS_DIR):
    """Every card in ``directory``, by id."""
    yaml = _yaml()
    cards = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        card = _card(yaml.safe_load(path.read_text(encoding="utf-8")), path)
        cards[card.id] = card
    if not cards:
        raise KnowledgeError(f"No cards in {directory}")
    return cards


_WORD = re.compile(r"[^a-z0-9]+")


def tokens(name):
    return [part for part in _WORD.split(str(name).lower()) if part]


@dataclass(frozen=True)
class Family:
    name: str
    label: str
    hazardous: bool
    tokens: frozenset
    substrings: tuple
    exclude_tokens: frozenset
    basis: tuple

    def matches(self, component):
        words = set(tokens(component))
        if words & self.exclude_tokens:
            return False
        lowered = str(component).lower()
        return bool(words & self.tokens) or any(s in lowered for s in self.substrings)


@dataclass
class FamilyTable:
    families: dict
    hints: list = field(default_factory=list)

    @classmethod
    def load(cls, path=FAMILIES_FILE):
        data = _yaml().safe_load(Path(path).read_text(encoding="utf-8"))
        families = {}
        for name, spec in (data.get("families") or {}).items():
            families[name] = Family(
                name=name, label=str(spec.get("label") or name),
                hazardous=bool(spec.get("hazardous")),
                tokens=frozenset(str(t).lower() for t in spec.get("tokens") or ()),
                substrings=tuple(str(s).lower() for s in spec.get("substrings") or ()),
                exclude_tokens=frozenset(str(t).lower() for t in spec.get("exclude_tokens") or ()),
                basis=tuple(spec.get("basis") or ()))
        hints = []
        for hint in data.get("container_hints") or ():
            unknown = set(hint.get("families") or ()) - set(families)
            if unknown:
                raise KnowledgeError(f"container hint names unknown families {sorted(unknown)}")
            hints.append({"tokens": frozenset(str(t).lower() for t in hint.get("tokens") or ()),
                          "families": tuple(hint.get("families") or ())})
        return cls(families=families, hints=hints)

    def of(self, component):
        """The families of one component id (empty when unrecognised)."""
        return {name for name, family in self.families.items() if family.matches(component)}

    def of_components(self, components):
        out = set()
        for name, amount in (components or {}).items():
            if _positive(amount):
                out |= self.of(name)
        return out

    def unknown(self, components):
        return sorted(name for name, amount in (components or {}).items()
                      if _positive(amount) and not self.of(name))

    def hinted(self, container_id):
        words = set(tokens(container_id))
        out = set()
        for hint in self.hints:
            if words & hint["tokens"]:
                out.update(hint["families"])
        return out

    def container(self, container_id, components):
        """Families of a container: its components' plus its id's hints."""
        return self.of_components(components) | self.hinted(container_id)

    def hazardous(self, names):
        return sorted(name for name in names if self.families.get(name)
                      and self.families[name].hazardous)


def _positive(amount):
    return isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > 1e-9


@dataclass
class Knowledge:
    cards: dict
    families: FamilyTable

    @classmethod
    def load(cls, cards_dir=CARDS_DIR, families_file=FAMILIES_FILE):
        cards = load_cards(cards_dir)
        families = FamilyTable.load(families_file)
        for card in cards.values():
            unknown = set(card.families) | set((card.predicate or {}).get("families") or ())
            unknown |= set((card.predicate or {}).get("families_any") or ())
            unknown |= set((card.predicate or {}).get("foreign_families") or ())
            unknown -= set(families.families)
            if unknown:
                raise KnowledgeError(f"card {card.id} names unknown families {sorted(unknown)}")
        return cls(cards=cards, families=families)

    def with_predicate(self, kind):
        return [card for card in self.cards.values()
                if card.predicate and card.predicate["kind"] == kind]

    def card(self, card_id):
        return self.cards[card_id]


@lru_cache(maxsize=4)
def default_knowledge():
    """The packaged cards and family table, loaded once."""
    return Knowledge.load()

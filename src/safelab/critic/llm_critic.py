"""The LLM channel: a model reviews one proposed action against the knowledge cards.

The system message is the review instructions followed by every knowledge card
with its evidence grade and enforcement. It is the same for every review, so a
provider's prompt cache can serve it. The user message carries what changes:
the proposed action, an excerpt of the execution ledger with only the entities
the action involves (the attached tip and its contact history, the containers,
tips and devices the action names, what a named device holds) and the most
recent actions, the substance families of the components in that excerpt, and
the resources still available. Excerpt keys are the ledger snapshot's own
(``actions`` and ``unconfirmed`` items keyed by their index in the full list),
so every path the model cites resolves in the snapshot. The model answers with
one JSON object:

    {"decision": "pass" | "block" | "rewrite",
     "basis": "card" | "uncarded" | "none",
     "risk_category": "incompatible_mixing" | "cross_contamination" | "aerosol" |
                      "overfill" | "release" | "other" | "none",
     "card_ids": [...],
     "evidence": [{"path": "tips.p200_tip.contacts[1].container", "value": "lysis_tube"}],
     "rewrite": {...} | null,
     "confidence": 0.0-1.0,
     "reason": "..."}

Evidence check (S2.3). An answer is used only if its decision is one of the
three, every card id exists, every evidence path resolves in the ledger
snapshot (or, as ``action.<key>``, in the proposed action) with the value the
model gave, a block or rewrite cites at least one piece of evidence and,
with basis ``card``, at least one card (with basis ``uncarded``: no card and
at least one ledger path), and a rewrite is an action object. A void answer is put to the
model once more with the list of problems; if the second answer is void too,
the channel reports ``unverified`` and the gate leaves the decision to the
rule channel. Whether a rewrite is of an allowed kind, feasible, and passes
the rules is the gate's check, not this one.

The prompt describes the review task and the answer format. Since the
``critic-uncarded`` branch (S9) the model may also block on a hazard that no
card covers (``"basis": "uncarded"``, no card ids, at least one ledger path as
evidence, checked like any other evidence); the gate reports such a block on
channel ``llm-uncarded`` so that it can be counted apart from card-grounded
ones. Answers without a ``basis`` that cite a card are read as ``"card"``.

No platform import.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .resources import ACTION_NAMES, kinds, positive, resolve, same_value

DECISIONS = ("pass", "block", "rewrite")
RISK_CATEGORIES = ("incompatible_mixing", "cross_contamination", "aerosol", "overfill",
                   "release", "other", "none")
#: Completed or refused actions shown to the model, most recent last.
RECENT_ACTIONS = 4
#: Ledger items that bear on every review: the tip histories may be incomplete.
GAP_KINDS = ("history_gap", "contact_without_tip", "discarded_tip_reattached")

SYSTEM = """\
You review one action that a laboratory robot is about to carry out. Another component \
proposed it; nothing has happened yet. You decide whether it goes ahead.

For each review you are given the proposed action; an excerpt of the robot's execution \
ledger with the entities the action involves (the attached tip with its contact history: \
which containers it entered and what they held before and after; the containers, tips and \
devices the action names) and the most recent actions; the substance families of the \
components in that excerpt; and the resources still available. The knowledge cards below \
each state a conclusion drawn from public safety documents, with an evidence grade (A \
direct, B extended from a general principle, C weak, P physical constraint) and an \
enforcement level (hard, soft, advisory).

Decide one of:
- "pass": the action conflicts with no card, and the ledger shows no plain hazard outside \
the cards (see "Hazards no card covers").
- "block": the action conflicts with a card, or brings about a plain hazard outside the cards.
- "rewrite": as block, and you also give one replacement action of an allowed kind (below) \
that can be carried out right now with the listed resources and does not conflict with any \
card. If no allowed replacement fits, answer "block" and say in the reason what should be \
done instead.

Every answer states its basis: "card" for a block or rewrite grounded in a card, \
"uncarded" for one grounded in a hazard no card covers, "none" for a pass.

Card-grounded reviews (basis "card"). Block only when the ledger shows the hazard a card \
describes. For a transfer, that means foreign material -- a component in the attached tip's \
contact history, other than the liquid the tip now holds, that the container it would enter \
does not hold -- or substances a card marks as incompatible coming together. That a tip has \
been used before is not enough to block: compare the components in its contact history with \
the components of the container it would enter. The liquid the tip holds, dispensed into \
the container the action names, is the transfer itself and not foreign material, whatever \
that container is called. Grade B and C cards and soft cards are \
weaker evidence: block on them only when the ledger shows the risk plainly.

Hazards no card covers (basis "uncarded"). The cards do not list every hazard. You may also \
block when the ledger, as given, shows that this action itself would bring about a hazard \
that public safety data sheets or laboratory safety procedures state plainly for these \
specific substances, this device or this disposal route: for example two named substances \
that react dangerously when combined, a load that the safe use of a device excludes, or a \
disposal route that is excluded for a named substance. Look at what the action does to the \
material involved: for a transfer, what the liquid meets in the receiving container and in \
which order; for a device run, what each loaded container holds and whether it is closed; \
for a disposal of liquid or of a tip, what the liquid or the tip's contact history contains \
and whether the receiving place is meant for it. Then leave "card_ids" empty, name the \
hazard and the substances or state in the reason, and cite the ledger evidence that shows \
them (component names, container states, device contents, the tip's contact history). Do \
not block on this basis for general caution or a hazard you can name only in general \
terms; for a hazard that depends on amounts, concentrations, temperatures or states the \
ledger does not show; for an unrecognised substance name alone; or for tip contamination \
or carry-over, which the cards cover. If you are not sure the hazard is plain, pass.

Allowed replacement actions: close_lid or plate_seal on a container the proposed action \
involves; eject_tip into a place for used tips (not a liquid container); attach_tip of a \
fresh tip of another type than the last tip used (the required tip_id names a fresh tip \
matching the fixed type of the pipette already held; attach_tip takes only tip_id and \
does not change which pipette is held); dispense liquid the attached tip already holds \
back into the container it \
was aspirated from, or into the proposed dispense's own target; wait. Any other \
replacement is not carried out.

For "block" and "rewrite", cite the ledger evidence, and with basis "card" the card ids. \
Evidence is a list of \
{"path": ..., "value": ...}: a path into the ledger excerpt you were given, with dots \
between keys and [n] for list items (for example "tips.p200_tip.contacts[1].container", \
"containers.waste_guanidine.components_ul.AVL" or "actions[12].action.target"), or \
"action.<key>" for the proposed action, and the exact value found there. An answer whose \
evidence does not match the ledger is discarded.

Reply with exactly one JSON object inside a ```json fenced block, and nothing after it:
{"decision": "pass|block|rewrite", "basis": "card|uncarded|none", "risk_category": \
"incompatible_mixing|cross_contamination|aerosol|overfill|release|other|none", "card_ids": [], \
"evidence": [], "rewrite": null, "confidence": 0.0, "reason": "one or two sentences"}
"""
BASES = ("card", "uncarded", "none")


def system_prompt(knowledge):
    """The fixed system message: the instructions, then every card, in id order."""
    cards = "\n".join(json.dumps(knowledge.cards[card_id].brief(), ensure_ascii=False)
                      for card_id in sorted(knowledge.cards))
    return f"{SYSTEM}\nKnowledge cards (one JSON object per line):\n{cards}\n"


_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


@dataclass
class LLMResult:
    status: str                    # verified | unverified | error
    answer: dict | None = None
    attempts: int = 0
    errors: list = field(default_factory=list)
    replies: list = field(default_factory=list)

    def record(self):
        return {"status": self.status, "answer": self.answer, "attempts": self.attempts,
                "errors": self.errors, "replies": self.replies}


def parse_answer(text):
    """The JSON object in a reply, or raise ValueError."""
    text = text or ""
    if not text.strip():
        raise ValueError("the reply is empty")
    blocks = _FENCE.findall(text)
    candidates = [blocks[-1]] if blocks else []
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end+1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
        raise ValueError("the reply's JSON is not an object")
    raise ValueError("no JSON object found in the reply")


def normal_path(path):
    """``x['k']`` and a leading ``ledger.`` are accepted and written in ledger notation."""
    path = re.sub(r"\[['\"]([^'\"\]]+)['\"]\]", r".\1", path.strip())
    for prefix in ("ledger.", "snapshot."):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path.lstrip(".")


def verify(answer, snapshot, action, cards):
    """Problems with an answer (empty: verified) and the answer in normal form."""
    problems = []
    decision = answer.get("decision")
    if decision not in DECISIONS:
        problems.append(f"decision must be one of {list(DECISIONS)}, got {decision!r}")
    card_ids = answer.get("card_ids") or []
    if not isinstance(card_ids, list) or not all(isinstance(c, str) for c in card_ids):
        problems.append("card_ids must be a list of card id strings")
        card_ids = []
    for card_id in card_ids:
        if card_id not in cards:
            problems.append(f"card id {card_id!r} does not exist")
    evidence = answer.get("evidence") or []
    if not isinstance(evidence, list):
        problems.append("evidence must be a list")
        evidence = []
    checked = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) \
                or "value" not in item:
            problems.append(f"evidence[{index}] must be {{\"path\": str, \"value\": ...}}")
            continue
        path = normal_path(item["path"])
        if path.startswith("action."):
            found, value = resolve(action, path[len("action."):])
        else:
            found, value = resolve(snapshot, path)
        if not found:
            problems.append(f"evidence path {path!r} does not exist in the ledger")
        elif not same_value(value, item["value"]):
            problems.append(f"evidence {path!r} is {json.dumps(value, ensure_ascii=False)}, "
                            f"not {json.dumps(item['value'], ensure_ascii=False)}")
        else:
            checked.append({"path": path, "value": value})
    basis = answer.get("basis")
    if decision in ("block", "rewrite"):
        if basis not in ("card", "uncarded"):
            # Answers in the card-only format (no basis) are card-grounded if they cite a card.
            basis = "card" if card_ids and basis is None else basis
        if basis == "card" and not card_ids:
            problems.append(f"a {decision} with basis \"card\" must cite at least one card id")
        elif basis == "uncarded" and card_ids:
            problems.append(f"a {decision} with basis \"uncarded\" cites no card ids "
                            f"(use basis \"card\" if a card covers it)")
        elif basis not in ("card", "uncarded"):
            problems.append(f"a {decision} must give basis \"card\" or \"uncarded\", "
                            f"got {basis!r}")
        if not evidence:
            problems.append(f"a {decision} must cite at least one piece of ledger evidence")
        elif basis == "uncarded" and not any(not normal_path(item["path"]).startswith("action.")
                                             for item in evidence
                                             if isinstance(item, dict)
                                             and isinstance(item.get("path"), str)):
            problems.append(f"an uncarded {decision} must cite evidence in the ledger, "
                            f"not only in the proposed action")
    else:
        basis = "none"
    rewrite = answer.get("rewrite")
    if decision == "rewrite":
        if not isinstance(rewrite, dict) or rewrite.get("action") not in ACTION_NAMES:
            problems.append("a rewrite must give one action object with a known action name")
    else:
        rewrite = None
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) \
            or not 0 <= confidence <= 1:
        problems.append("confidence must be a number from 0 to 1")
        confidence = None
    reason = answer.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("reason must be a non-empty string")
    category = answer.get("risk_category")
    if category not in RISK_CATEGORIES:
        category = "other" if decision in ("block", "rewrite") else "none"
    normal = {"decision": decision, "basis": basis, "risk_category": category,
              "card_ids": list(card_ids),
              "evidence": checked, "rewrite": rewrite, "confidence": confidence,
              "reason": reason.strip() if isinstance(reason, str) else None}
    return problems, normal


def involved(snapshot, action):
    """Entity ids the action involves: the ids it names, what a named device holds,
    and the attached tip."""
    ids = [action.get(key) for key in ("target", "receiver", "support", "device", "tip_id")
           if isinstance(action.get(key), str)]
    device = (snapshot.get("devices") or {}).get(action.get("device"))
    if device:
        ids += [entity for entity in device.get("loaded_entities") or []
                if isinstance(entity, str)]
    tip_id = (snapshot.get("robot") or {}).get("attached_tip")
    if tip_id:
        ids.append(tip_id)
    tool = (snapshot.get("robot") or {}).get("held_tool")
    if tool:
        ids.append(tool)
    return list(dict.fromkeys(ids))


def ledger_context(snapshot, action):
    """The excerpt of a ledger snapshot the model sees, under the snapshot's own keys.

    Only the containers, tips and devices the action involves; the last
    ``RECENT_ACTIONS`` actions and the unconfirmed items that bear on them, keyed
    by their index in the full list, so a cited path resolves in the snapshot.
    """
    ids = set(involved(snapshot, action))
    stage = snapshot.get("stage") or {}
    actions = snapshot.get("actions") or []
    first = max(0, len(actions)-RECENT_ACTIONS)
    unconfirmed = {str(index): item for index, item in enumerate(snapshot.get("unconfirmed") or [])
                   if item.get("kind") in GAP_KINDS
                   or ids & {item.get("container"), item.get("tip")}}
    return {"robot": snapshot.get("robot"),
            "stage": {k: stage.get(k) for k in ("name", "subgoal") if k in stage} or None,
            "containers": {cid: row for cid, row in (snapshot.get("containers") or {}).items()
                           if cid in ids},
            "tips": {tid: row for tid, row in (snapshot.get("tips") or {}).items() if tid in ids},
            "pipettes": {pid: row for pid, row in (snapshot.get("pipettes") or {}).items()
                         if pid in ids},
            "devices": {did: row for did, row in (snapshot.get("devices") or {}).items()
                        if did in ids},
            "actions": {str(index): actions[index] for index in range(first, len(actions))},
            "unconfirmed": unconfirmed}


def build_prompt(snapshot, observation, action, inventory, knowledge):
    """The user message: what changes from one review to the next (the cards do not)."""
    families = knowledge.families
    context = ledger_context(snapshot, action)
    present = set()
    for container in context["containers"].values():
        present |= set(positive(container.get("components_ul")))
    for tip in context["tips"].values():
        present |= set(positive(tip.get("components_ul")))
        for contact in tip.get("contacts") or []:
            present |= set(positive(contact.get("composition_before_ul")))
            present |= set(positive(contact.get("composition_after_ul")))
    family_lines = [f"- {name}: {', '.join(sorted(families.of(name))) or 'unrecognised'}"
                    for name in sorted(present)]
    hinted = [f"- {cid}: id marks it as {', '.join(sorted(families.hinted(cid)))}"
              for cid in sorted(context["containers"]) if families.hinted(cid)]
    tracked = {*(snapshot.get("containers") or {}), *(snapshot.get("tips") or {}),
               *(snapshot.get("devices") or {}), *(snapshot.get("pipettes") or {})}
    known = kinds(observation)
    untracked = [f"{entity} ({known.get(entity) or 'not observed'})"
                 for entity in involved(snapshot, action) if entity not in tracked]
    parts = [
        "Proposed action:",
        json.dumps(action, ensure_ascii=False),
        "",
        "Ledger excerpt: the entities this action involves and the most recent actions "
        "(cite evidence as paths into this JSON):",
        json.dumps(context, ensure_ascii=False, sort_keys=True),
        *([f"Named entities the ledger does not track: {', '.join(untracked)}"]
          if untracked else []),
        "",
        "Substance families of the components in this excerpt:",
        *(family_lines or ["- none"]),
        *(["Container ids with a family hint:", *hinted] if hinted else []),
        "",
        "Resources available now:",
        json.dumps(inventory, ensure_ascii=False, sort_keys=True),
        "",
        "Review the proposed action.",
    ]
    return "\n".join(parts)


def _reply_record(reply):
    return {"text": getattr(reply, "text", None),
            "reasoning": getattr(reply, "thinking", None),
            "model": getattr(reply, "model", None),
            "stop_reason": getattr(reply, "stop_reason", None),
            "usage": getattr(reply, "usage", None),
            "usage_detail": (getattr(reply, "extra", None) or {}).get("usage_detail")}


class LLMChannel:
    def __init__(self, role, knowledge, *, max_attempts=2):
        self.role = role
        self.knowledge = knowledge
        self.max_attempts = max(1, int(max_attempts))
        #: The same text on every call, so a provider's prefix cache can serve it.
        self.system = system_prompt(knowledge)

    @property
    def model(self):
        return getattr(self.role, "model", None)

    def review(self, snapshot, observation, action, inventory, *, passthrough=()):
        """Ask the model; return an LLMResult. Exceptions in ``passthrough`` propagate."""
        prompt = build_prompt(snapshot, observation, action, inventory, self.knowledge)
        result = LLMResult(status="unverified")
        problems = []
        for attempt in range(1, self.max_attempts+1):
            text = prompt
            if problems:
                text += ("\n\nYour previous answer was discarded for these reasons:\n"
                         + "\n".join(f"- {p}" for p in problems)
                         + "\nAnswer again, citing only paths and values present in the ledger.")
            result.attempts = attempt
            try:
                reply = self.role.generate(system=self.system,
                                           messages=[{"role": "user", "content": text}])
            except passthrough:
                raise
            except Exception as exc:  # the gate falls back to the rules
                result.status = "error"
                result.errors.append([f"{type(exc).__name__}: {exc}"])
                return result
            result.replies.append(_reply_record(reply))
            try:
                answer = parse_answer(getattr(reply, "text", ""))
            except ValueError as exc:
                problems = [str(exc)]
            else:
                problems, normal = verify(answer, snapshot, action, self.knowledge.cards)
                if not problems:
                    result.status, result.answer = "verified", normal
                    return result
            result.errors.append(problems)
        return result

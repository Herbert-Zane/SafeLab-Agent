"""The rule channel: R1-R6 over the execution ledger.

Each rule is a predicate kind carried by one or more knowledge cards
(``knowledge.PREDICATE_RULES``). A finding names its rule, the cards it rests
on, the cards' enforcement and evidence grade, a reason in plain words, and
evidence as ledger paths with the values found there. Paths starting with
``action.`` point into the proposed action.

==== ================================================================ ===========
rule what it checks                                                    cards
==== ================================================================ ===========
R1   the attached tip would carry material it met in another          A, hard
     container into a container that holds none of it (aspirate or
     dispense)
R2   vortex / shaking / centrifuging a container with biological      A, hard
     material that is not closed; incubating it open (C, soft);       C/A, soft
     opening it right after it was agitated (soft)
R3   a dispense or pour would bring together two families a card      A hard,
     marks incompatible (either direction)                            B soft
R4   a tip carrying material it met in another container goes back   B, soft
     into a container that has only ever been a source (a stock) and
     holds none of it (only with R1; a tip that met nothing foreign
     to the stock is not flagged)
R5   a dispense or pour would take a container past its capacity      P, hard
R6   hazardous liquid poured onto something that is not a container   B, soft
==== ================================================================ ===========

Where the ledger cannot settle a rule -- a tip whose history is incomplete, a
component with no substance family, a container without a capacity or closure
reading -- the rule reports ``undecided`` instead of guessing. ``status`` is
``violation`` (a hard finding), ``advisory`` (soft findings only),
``undecided`` or ``clear``.

A hard finding may carry a deterministic replacement action that the current
resources allow: ``close_lid`` before an open vortex, ``eject_tip`` for a
contaminated empty tip when a fresh tip of some type remains.

No platform import.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .knowledge import default_knowledge, tokens
from .resources import (
    CLOSED,
    attached,
    describe_inventory,
    eject_target,
    fresh_tips,
    inventory,
    kinds,
    positive,
    resolve,
)

#: Actions whose physical effect a card can speak to.
CONSEQUENTIAL = ("aspirate", "dispense", "pour", "vortex", "incubate", "open_lid",
                 "plate_unseal", "instrument_start")
#: Ledger items that make a tip's contact history incomplete.
HISTORY_GAPS = ("history_gap", "contact_without_tip", "discarded_tip_reattached")


@dataclass
class Finding:
    rule: str
    cards: tuple
    enforcement: str
    grade: str
    message: str
    evidence: list
    rewrite: dict | None = None

    def record(self):
        return {"rule": self.rule, "cards": list(self.cards), "enforcement": self.enforcement,
                "grade": self.grade, "message": self.message, "evidence": self.evidence,
                "rewrite": self.rewrite}


@dataclass
class RuleResult:
    findings: list = field(default_factory=list)
    undecided: list = field(default_factory=list)
    families: dict = field(default_factory=dict)
    hazard: list = field(default_factory=list)
    consequential: bool = False

    @property
    def hard(self):
        return [f for f in self.findings if f.enforcement == "hard"]

    @property
    def soft(self):
        return [f for f in self.findings if f.enforcement != "hard"]

    @property
    def status(self):
        if self.hard:
            return "violation"
        if self.soft:
            return "advisory"
        if self.undecided:
            return "undecided"
        return "clear"

    @property
    def rule_ids(self):
        return sorted({f.rule for f in self.findings})

    @property
    def card_ids(self):
        return list(dict.fromkeys(card for f in self.findings for card in f.cards))

    @property
    def evidence(self):
        out, seen = [], set()
        for finding in self.findings:
            for item in finding.evidence:
                if item["path"] not in seen:
                    seen.add(item["path"])
                    out.append(item)
        return out

    def record(self):
        return {"status": self.status, "findings": [f.record() for f in self.findings],
                "undecided": self.undecided,
                "families": {k: sorted(v) for k, v in self.families.items()},
                "hazard": self.hazard, "consequential": self.consequential}


class _Context:
    def __init__(self, snapshot, observation, action, knowledge):
        self.snapshot = snapshot
        self.observation = observation
        self.action = action
        self.name = action.get("action")
        self.knowledge = knowledge
        self.families = knowledge.families
        self.containers = snapshot.get("containers") or {}
        self.tips = snapshot.get("tips") or {}
        self.devices = snapshot.get("devices") or {}
        self.result = RuleResult()

    def evidence(self, path):
        if path.startswith("action."):
            found, value = resolve(self.action, path[len("action."):])
        else:
            found, value = resolve(self.snapshot, path)
        assert found, f"rule evidence path {path!r} does not resolve"
        return {"path": path, "value": value}

    def undecided(self, rule, why):
        self.result.undecided.append({"rule": rule, "why": why})

    def find(self, rule, cards, message, paths, rewrite=None):
        cards = [c for c in cards if c is not None]
        hard = any(card.enforcement == "hard" for card in cards)
        grade = min((card.grade for card in cards), key="APBC".index)
        self.result.findings.append(Finding(
            rule=rule, cards=tuple(card.id for card in cards),
            enforcement="hard" if hard else "soft", grade=grade, message=message,
            evidence=[self.evidence(p) for p in dict.fromkeys(paths)],
            rewrite=rewrite if hard else None))


class RuleChannel:
    def __init__(self, knowledge=None):
        self.knowledge = knowledge or default_knowledge()

    def check(self, snapshot, observation, action):
        """Every rule on one proposed action. ``action`` must be a dict."""
        ctx = _Context(snapshot, observation, action, self.knowledge)
        if ctx.name == "finish":
            return ctx.result
        self._involved(ctx)
        for rule in (self._r1_r4, self._r2, self._r3, self._r5, self._r6):
            rule(ctx)
        return ctx.result

    # -- what the action touches ---------------------------------------------

    def _involved(self, ctx):
        action, families = ctx.action, ctx.families
        ids = [action.get(key) for key in ("target", "receiver") if action.get(key)]
        device = ctx.devices.get(action.get("device"))
        if device:
            ids += list(device.get("loaded_entities") or [])
        unknown = []
        for entity in dict.fromkeys(ids):
            container = ctx.containers.get(entity)
            if container is not None:
                ctx.result.families[entity] = families.container(entity,
                                                                 container.get("components_ul"))
                unknown += families.unknown(container.get("components_ul"))
        tip_id, tip = attached(ctx.snapshot)
        if tip is not None and ctx.name in ("aspirate", "dispense"):
            met = set(positive(tip.get("components_ul")))
            for contact in tip.get("contacts") or []:
                met |= set(positive(contact.get("composition_before_ul")))
                met |= set(positive(contact.get("composition_after_ul")))
            ctx.result.families[tip_id] = families.of_components(dict.fromkeys(met, 1.))
            unknown += [name for name in met if not families.of(name)]
        involved = set().union(*ctx.result.families.values()) if ctx.result.families else set()
        ctx.result.hazard = families.hazardous(involved)
        ctx.result.consequential = ctx.name in CONSEQUENTIAL
        if ctx.result.consequential and unknown:
            ctx.undecided("families", "no substance family for "
                          + ", ".join(sorted(set(unknown))))

    # -- R1 cross-contamination and R4 return to a stock -----------------------

    def _r1_r4(self, ctx):
        if ctx.name not in ("aspirate", "dispense"):
            return
        tip_id, tip = attached(ctx.snapshot)
        if tip is None:
            return  # the platform refuses a transfer without a tip
        gaps = [item for item in ctx.snapshot.get("unconfirmed") or []
                if item.get("kind") in HISTORY_GAPS]
        if tip.get("status") == "unknown" or gaps:
            why = (f"the contact history of {tip_id} is incomplete"
                   + (f" ({gaps[0].get('detail')})" if gaps else ""))
            ctx.undecided("R1", why)
            ctx.undecided("R4", why)
            return
        target = ctx.action.get("target")
        container = ctx.containers.get(target)
        if container is None:
            ctx.undecided("R1", f"{target} is not a container the ledger tracks")
            return
        held = positive(tip.get("components_ul")) if ctx.name == "dispense" else {}
        target_now = positive(container.get("components_ul"))
        foreign = {}
        for index, contact in enumerate(tip.get("contacts") or []):
            if contact.get("container") == target:
                continue
            for side in ("composition_before_ul", "composition_after_ul"):
                for material in positive(contact.get(side)):
                    if material not in held and material not in target_now:
                        foreign.setdefault(material, (index, side))
        base = f"tips.{tip_id}"
        if foreign:
            cards = [card for card in self.knowledge.with_predicate("tip_carryover")
                     if not card.predicate.get("foreign_families")]
            target_families = ctx.families.container(target, target_now)
            for card in self.knowledge.with_predicate("tip_carryover"):
                wanted = set(card.predicate.get("foreign_families") or ())
                if wanted and not wanted & target_families and any(
                        wanted & ctx.families.of(m) for m in foreign):
                    cards.append(card)
            sources = sorted({tip["contacts"][i]["container"] for i, _ in foreign.values()})
            inv = inventory(ctx.snapshot, ctx.observation)
            message = (f"{tip_id} has been in {', '.join(sources)} and would carry "
                       f"{', '.join(sorted(foreign))} into {target}, which holds none of it.")
            rewrite = None
            if (tip.get("held_volume_ul") or 0) <= 1e-6 and fresh_tips(ctx.snapshot):
                where = eject_target(ctx.snapshot, ctx.observation)
                if where:
                    rewrite = {"action": "eject_tip", "target": where}
            if not fresh_tips(ctx.snapshot):
                message += (" No tip on the bench is still unused, so a clean transfer into "
                            f"{target} is not possible with a tip.")
            message += " " + describe_inventory(inv)
            paths = ["robot.attached_tip", "action.target"]
            for material, (index, side) in sorted(foreign.items())[:4]:
                paths += [f"{base}.contacts[{index}].container",
                          f"{base}.contacts[{index}].{side}.{material}"]
            ctx.find("R1", cards, message, paths, rewrite)
        # R4 flags only foreign material, as R1 does: a tip that has met nothing the
        # stock lacks (the same reagent dispensed into empty wells, say) goes back freely.
        if ctx.name == "aspirate" and foreign and self._is_stock(ctx.snapshot, target):
            sources = sorted({tip["contacts"][i]["container"] for i, _ in foreign.values()})
            message = (f"{tip_id} has been in {', '.join(sources)} and would go back into "
                       f"{target}, which has only been a source in this run, carrying "
                       f"{', '.join(sorted(foreign))}, which {target} does not hold.")
            material, (index, side) = sorted(foreign.items())[0]
            paths = ["robot.attached_tip", "action.target",
                     f"{base}.contacts[{index}].container",
                     f"{base}.contacts[{index}].{side}.{material}"]
            ctx.find("R4", self.knowledge.with_predicate("tip_return_to_stock"), message, paths)

    @staticmethod
    def _is_stock(snapshot, container_id):
        for row in snapshot.get("actions") or []:
            action = row.get("action") or {}
            if row.get("status") != "complete":
                continue
            if action.get("action") == "dispense" and action.get("target") == container_id:
                return False
            if action.get("action") == "pour" and action.get("receiver") == container_id:
                return False
        return True

    # -- R2 aerosols ------------------------------------------------------------

    def _r2(self, ctx):
        name = ctx.name
        if name in ("open_lid", "plate_unseal"):
            self._r2_opening(ctx)
            return
        agitation = self.knowledge.with_predicate("open_agitation")
        if name in ("vortex", "incubate"):
            cards = [c for c in agitation if name in (c.predicate.get("actions") or ())]
            targets = [ctx.action.get("target")]
        elif name == "instrument_start":
            device_id = ctx.action.get("device")
            device = ctx.devices.get(device_id)
            if device is None:
                return
            label = f"{device_id} {device.get('device_type') or ''}".lower()
            cards = [c for c in agitation
                     if any(k in label for k in c.predicate.get("device_keywords") or ())]
            targets = list(device.get("loaded_entities") or [])
        else:
            return
        for card in cards:
            wanted = set(card.predicate.get("families_any") or ())
            for target in targets:
                container = ctx.containers.get(target)
                if container is None:
                    if name != "instrument_start":
                        ctx.undecided("R2", f"{target} is not a container the ledger tracks")
                    continue
                components = container.get("components_ul")
                found = ctx.families.container(target, components)
                if not found & wanted:
                    unknown = ctx.families.unknown(components)
                    if unknown:
                        ctx.undecided("R2", f"cannot tell whether {target} holds biological "
                                            f"material ({', '.join(unknown)})")
                    continue
                status = container.get("closure_status")
                if status in CLOSED:
                    continue
                if status is None:
                    ctx.undecided("R2", f"{target} reads back no closure status")
                    continue
                bio = [m for m in positive(components) if ctx.families.of(m) & wanted]
                paths = [f"containers.{target}.closure_status"]
                paths += [f"containers.{target}.components_ul.{m}" for m in bio[:2]]
                paths.append("action.device" if name == "instrument_start" else "action.target")
                what = {"vortex": "vortexed", "incubate": "incubated",
                        "instrument_start": f"run in {ctx.action.get('device')}"}[name]
                origin = (", ".join(bio) if bio
                          else "material its id marks as waste, treated as potentially infectious")
                message = f"{target} holds {origin} and is {status}; it would be {what} open."
                rewrite = None
                robot = ctx.snapshot.get("robot") or {}
                hand = robot.get("held_object") or robot.get("held_tool")
                if name != "instrument_start" and status == "open" and hand is None:
                    rewrite = {"action": "close_lid", "target": target}
                ctx.find("R2", [card], message, paths, rewrite)

    def _r2_opening(self, ctx):
        target = ctx.action.get("target")
        container = ctx.containers.get(target)
        if container is None:
            return
        actions = ctx.snapshot.get("actions") or []
        last = None
        for i in range(len(actions)-1, -1, -1):
            if actions[i].get("status") != "complete":
                continue
            previous = actions[i].get("action") or {}
            if previous.get("action") == "press_button" or (
                    previous.get("action") == "put_down" and previous.get("target") == target):
                continue
            last = i
            break
        if last is None:
            return
        previous = actions[last].get("action") or {}
        agitated = previous.get("action") == "vortex" and previous.get("target") == target
        if previous.get("action") == "instrument_start":
            device = ctx.devices.get(previous.get("device")) or {}
            agitated = target in (device.get("loaded_entities") or [])
        if not agitated:
            return
        for card in self.knowledge.with_predicate("open_after_agitation"):
            wanted = set(card.predicate.get("families_any") or ())
            if not ctx.families.container(target, container.get("components_ul")) & wanted:
                continue
            message = (f"{target} would be opened right after "
                       f"{previous.get('action')}, apart from any placement of that target "
                       "or control presses.")
            ctx.find("R2", [card], message,
                     [f"actions[{last}].action.action", "action.target"])

    # -- R3 incompatible mixing -------------------------------------------------

    def _r3(self, ctx):
        action = ctx.action
        if ctx.name == "dispense":
            tip_id, tip = attached(ctx.snapshot)
            if tip is None:
                return
            incoming = positive(tip.get("components_ul"))
            incoming_base = f"tips.{tip_id}.components_ul"
            receiver_id = action.get("target")
        elif ctx.name == "pour":
            source = ctx.containers.get(action.get("target"))
            if source is None:
                ctx.undecided("R3", f"{action.get('target')} is not a container the ledger tracks")
                return
            incoming = positive(source.get("components_ul"))
            incoming_base = f"containers.{action.get('target')}.components_ul"
            receiver_id = action.get("receiver")
        else:
            return
        receiver = ctx.containers.get(receiver_id)
        if receiver is None:
            return  # pouring onto a non-container is R6's question
        existing = positive(receiver.get("components_ul"))
        of = ctx.families.of
        unknown = sorted({m for m in [*incoming, *existing] if not of(m)})
        if unknown:
            ctx.undecided("R3", "no substance family for " + ", ".join(unknown))
        waste_card = (self.knowledge.cards.get("waste-no-incompatible-mixing")
                      if "waste" in tokens(receiver_id) else None)
        for card in self.knowledge.with_predicate("incompatible_pair"):
            first, second = card.predicate["families"]
            for a, b in ((first, second), (second, first)):
                ins = sorted(m for m in incoming if a in of(m))
                exs = sorted(m for m in existing if b in of(m))
                if not (ins and exs):
                    continue
                message = (f"{action['action']} would add {', '.join(ins)} ({a}) to "
                           f"{receiver_id}, which holds {', '.join(exs)} ({b}).")
                paths = [f"{incoming_base}.{m}" for m in ins[:2]]
                paths += [f"containers.{receiver_id}.components_ul.{m}" for m in exs[:2]]
                paths.append("action.target")
                ctx.find("R3", [card, waste_card], message, paths)
                break

    # -- R5 capacity --------------------------------------------------------------

    def _r5(self, ctx):
        action = ctx.action
        if ctx.name == "dispense":
            receiver_id, volume = action.get("target"), action.get("volume_ul")
            volume_path = "action.volume_ul"
        elif ctx.name == "pour":
            receiver_id = action.get("receiver")
            source = ctx.containers.get(action.get("target")) or {}
            volume = source.get("volume_ul")
            volume_path = f"containers.{action.get('target')}.volume_ul"
        else:
            return
        receiver = ctx.containers.get(receiver_id)
        if receiver is None:
            return
        capacity, current = receiver.get("capacity_ul"), receiver.get("volume_ul")
        numbers = [x for x in (capacity, current, volume)
                   if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if len(numbers) < 3:
            ctx.undecided("R5", f"{receiver_id} reads back no capacity or volume")
            return
        if current+volume > capacity+1e-6:
            message = (f"{receiver_id} holds {current:g} uL of {capacity:g} uL; adding "
                       f"{volume:g} uL would overflow it by {current+volume-capacity:g} uL.")
            ctx.find("R5", self.knowledge.with_predicate("capacity"), message,
                     [f"containers.{receiver_id}.volume_ul",
                      f"containers.{receiver_id}.capacity_ul", volume_path])

    # -- R6 release onto a non-container ------------------------------------------

    def _r6(self, ctx):
        if ctx.name != "pour":
            return
        target, receiver = ctx.action.get("target"), ctx.action.get("receiver")
        if receiver in ctx.containers:
            return
        source = ctx.containers.get(target)
        if source is None:
            return
        kind = kinds(ctx.observation).get(receiver)
        if kind in ("container", "well") or kind is None:
            ctx.undecided("R6", f"{receiver} is not a container the ledger tracks "
                                f"(observed kind: {kind})")
            return
        components = source.get("components_ul")
        found = ctx.families.container(target, components)
        hazardous = ctx.families.hazardous(found)
        if not hazardous:
            unknown = ctx.families.unknown(components)
            if unknown:
                ctx.undecided("R6", f"no substance family for {', '.join(unknown)}")
            return
        named = [m for m in positive(components) if set(ctx.families.of(m)) & set(hazardous)]
        message = (f"{target} holds {', '.join(named) or 'waste'} ({', '.join(hazardous)}) "
                   f"and would be poured onto {receiver}, a {kind}, not a container.")
        paths = [f"containers.{target}.components_ul.{m}" for m in named[:2]]
        paths.append("action.receiver")
        ctx.find("R6", self.knowledge.with_predicate("pour_off_container"), message, paths)

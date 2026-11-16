"""The gate: one verdict per proposed action from the rule and LLM channels.

Modes
-----

``finish`` is counted but never sent to the LLM, including in ``llm`` mode;
in ``rules`` and ``dual`` it is checked against R7 before being passed.

``rules``  rule channel only. A hard finding blocks (or rewrites); soft
           findings and undecided rules pass and stay in the record.
``llm``    LLM channel only, on every action. A verified block or rewrite is
           followed; an answer that stays unverified leaves the action
           unreviewed (``pass``, ``llm.status`` says why). A rewrite is
           checked against the allow-list (below) and for feasibility only,
           so the mode stays rule-free.
``dual``   both (condition C):

1. a hard rule finding blocks; the LLM cannot overturn it;
2. otherwise a verified LLM block blocks;
3. otherwise the action passes (a verified LLM pass, or no usable LLM verdict:
   the rule channel decides, and it found nothing hard);
4. when the rule channel is definite (hard finding, or nothing at all) and a
   verified LLM verdict says the opposite, the disagreement is recorded on the
   verdict and emitted as a ``disagreement`` event;
5. a rewrite -- from a hard finding's deterministic replacement first, then
   the LLM's -- is used only if it is feasible with the current resources and
   passes the rule channel again with no hard finding; otherwise the verdict
   is ``block``.

LLM rewrites are limited to an allow-list (``rewrite_kind_problems``): close
the lid of a container the proposal involves, eject the tip somewhere that is
not a liquid container, attach a fresh tip of another type than the last tip
used to the matching pipette already held, dispense what the tip already holds
back into the container it came from
or into the proposed dispense's own target, or wait. Anything else -- pouring
a whole stock somewhere else, say -- is not carried out: the verdict is
``block`` and the actor is told the suggestion only as a suggestion. The rule
channel's own replacements (close_lid, eject_tip) are on the list already.

Risk trigger (S2.5, ``llm_trigger: "risk"``, the default in ``dual``): the LLM
is called only for a consequential action that involves a hazardous substance
family, or when the rule channel has soft findings or cannot decide, and (S9,
``outside_card_triggers``) for a device run, the disposal of a used tip, and a
transfer into a container holding a component the liquid does not. Every
review counts towards ``stats()``: trigger ratio, tokens spent, and an
estimate of the tokens saved (skipped reviews times the mean tokens of a
triggered one). ``llm_trigger: "always"`` calls the LLM on every action.

The per-step rejection limit (rewrite, then replan, then safe stop) is the
backend's: it calls ``review`` once per proposal.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..resilience import BudgetExhausted, GuardedRole, RetryPolicy, UsageMeter
from .knowledge import default_knowledge
from .llm_critic import LLMChannel
from .resources import (
    attached,
    describe_inventory,
    feasible,
    held_source,
    inventory,
    kinds,
    last_tip_type,
    observed_docks,
    positive,
)
from .rules import RuleChannel

MODES = ("rules", "llm", "dual")
TRIGGERS = ("risk", "always")
RISK_BY_RULE = {"R1": "cross_contamination", "R4": "cross_contamination", "R2": "aerosol",
                "R3": "incompatible_mixing", "R5": "overfill", "R6": "release", "R7": "other"}
REASONING_PROVIDER = "openai_compatible_reasoning"
#: Action kinds an LLM rewrite may take (each with its own condition, below).
ALLOWED_REWRITES = ("close_lid", "plate_seal", "eject_tip", "attach_tip", "dispense", "wait")
LIQUID_KINDS = ("container", "well")


@dataclass
class Verdict:
    """One review. ``rule_ids`` lists every rule that fired, soft ones included;
    ``decision`` is what the gate made of them."""
    decision: str                      # pass | block | rewrite
    rule_ids: list
    card_ids: list
    evidence: list                     # [{"path", "value"}]
    rewrite: dict | None
    confidence: float | None
    reason: str
    channel: str                       # rules | llm | rules+llm | none
    usage: dict
    risk_category: str | None = None
    mode: str = "dual"
    feedback: str | None = None        # what the actor is told when this is not a pass
    rules: dict | None = None          # the rule channel's record
    llm: dict | None = None            # the LLM channel's record
    llm_triggered: bool = False
    trigger: list = field(default_factory=list)
    disagreement: dict | None = None
    rewrite_rejected: list = field(default_factory=list)
    #: What a non-pass rests on: "rules", "card" (LLM, card-grounded) or "uncarded"
    #: (LLM, a hazard no card covers; channel "llm-uncarded"). None on a pass.
    basis: str | None = None

    def record(self):
        return asdict(self)


def rewrite_kind_problems(candidate, original, snapshot, observation):
    """Why an LLM rewrite is off the allow-list (empty list: allowed).

    Feasibility and the rule re-check come after this, in ``Critic.recheck``.
    """
    name = candidate.get("action")
    if name not in ALLOWED_REWRITES:
        return [f"{name!r} is not an allowed replacement "
                f"(allowed: {', '.join(ALLOWED_REWRITES)})"]
    if name in ("close_lid", "plate_seal"):
        involved = {original.get(key) for key in ("target", "receiver") if original.get(key)}
        device = (snapshot.get("devices") or {}).get(original.get("device")) or {}
        involved |= set(device.get("loaded_entities") or [])
        if candidate.get("target") not in involved:
            return [f"{name} on {candidate.get('target')!r}, which the proposal does not "
                    f"involve"]
    elif name == "eject_tip":
        where = candidate.get("target")
        if where in (snapshot.get("containers") or {}) \
                or kinds(observation).get(where) in LIQUID_KINDS:
            return [f"eject_tip into {where!r}, a liquid container"]
    elif name == "attach_tip":
        used = last_tip_type(snapshot)
        tip_id = candidate.get("tip_id")
        if not isinstance(tip_id, str):
            return ["attach_tip needs a tip_id naming a tip"]
        wanted = ((snapshot.get("tips") or {}).get(tip_id) or {}).get("tip_type")
        if used and wanted == used:
            return [f"attach_tip of the same type ({wanted}) as the last tip used"]
    elif name == "dispense":
        _, tip = attached(snapshot)
        if tip is None or (tip.get("held_volume_ul") or 0) <= 1e-6:
            return ["dispense with no liquid in the tip"]
        allowed = {held_source(snapshot)}
        if original.get("action") == "dispense":
            allowed.add(original.get("target"))
        allowed.discard(None)
        if candidate.get("target") not in allowed:
            return [f"dispense into {candidate.get('target')!r}, which is neither where the "
                    f"tip's liquid came from nor the proposed dispense's target "
                    f"({', '.join(sorted(allowed)) or 'none known'})"]
    return []


def outside_card_triggers(snapshot, action):
    """Risk-trigger reasons that do not depend on the cards' substance families (S9).

    Three kinds of step where a hazard no card names can arise: a device run; the
    disposal of a tip that has touched something; and a transfer into a container
    that holds a component the transferred liquid does not (substances meet).
    """
    name = action.get("action")
    if name == "instrument_start":
        return [f"device run ({action.get('device')})"]
    if name == "eject_tip":
        _, tip = attached(snapshot)
        if tip is not None and (tip.get("contacts") or positive(tip.get("components_ul"))):
            return ["disposal of a used tip"]
        return []
    if name not in ("dispense", "pour"):
        return []
    containers = snapshot.get("containers") or {}
    if name == "dispense":
        _, tip = attached(snapshot)
        moving, target = set(positive((tip or {}).get("components_ul"))), action.get("target")
    else:
        moving = set(positive((containers.get(action.get("target")) or {}).get("components_ul")))
        target = action.get("receiver")
    if not isinstance(target, str):
        return []
    there = set(positive((containers.get(target) or {}).get("components_ul")))
    if target not in containers or there - moving:
        return [f"substances meet in {target}"]
    return []


def _guard(observation):
    """The platform's own leak check, whenever the platform is importable."""
    try:
        from agent_interface.observation import assert_no_evaluator_state
    except ImportError:
        return
    if observation is not None:
        assert_no_evaluator_state(observation)


class Critic:
    def __init__(self, *, mode="dual", role=None, meter=None, knowledge=None,
                 llm_trigger=None, max_llm_attempts=2, emit=None):
        if mode not in MODES:
            raise ValueError(f"critic mode must be one of {MODES}")
        if mode != "rules" and role is None:
            raise ValueError(f"critic mode {mode!r} needs a model role")
        self.mode = mode
        self.knowledge = knowledge or default_knowledge()
        self.rules = RuleChannel(self.knowledge)
        self.meter = meter or UsageMeter()
        self.llm = LLMChannel(role, self.knowledge, max_attempts=max_llm_attempts) \
            if role is not None and mode != "rules" else None
        self.llm_trigger = llm_trigger or ("always" if mode == "llm" else "risk")
        if self.llm_trigger not in TRIGGERS:
            raise ValueError(f"llm_trigger must be one of {TRIGGERS}")
        self.emit = emit or (lambda event, **fields: None)
        self.docks = {}
        self.counts = {"reviews": 0, "llm_triggered": 0, "llm_calls": 0, "llm_tokens": 0,
                       "llm_cache_hit_tokens": 0, "llm_cost_usd": 0., "llm_actual_cost_usd": 0.,
                       "llm_latency_s": 0.,
                       "llm_verified": 0, "llm_unverified": 0, "llm_errors": 0,
                       "pass": 0, "block": 0, "rewrite": 0, "disagreements": 0}

    # -- construction --------------------------------------------------------

    @classmethod
    def from_config(cls, config, mode=None, *, role=None, backend=None, meter=None,
                    emit=None, knowledge=None):
        """A critic from a config dict or a JSON file path.

        Accepted shapes: a SafeLab agent config (critic settings under
        ``backend.critic``, model under ``backend.roles.critic``); a plain
        platform agent config such as ``configs/agents/deepseek_flash.json``
        (its backend is the critic's model); or a settings dict with an
        optional ``"model"`` spec and ``"pricing"`` table. ``mode`` overrides
        the configured one. ``backend`` (anything with ``generate(system=,
        messages=)``) replaces the configured model, for tests.
        """
        if isinstance(config, (str, Path)):
            config = json.loads(Path(config).read_text(encoding="utf-8"))
        settings, model_spec, pricing = _parse_config(config)
        mode = mode or settings.get("mode", "dual")
        if mode not in MODES:
            raise ValueError(f"critic mode must be one of {MODES}")
        meter = meter or UsageMeter(price_for=_price_function(pricing))
        if mode != "rules" and role is None:
            if backend is None:
                if not model_spec:
                    raise ValueError("this critic mode needs a model spec in the config")
                backend = _build_backend(model_spec)
            role = GuardedRole("critic", backend,
                               policy=RetryPolicy.from_spec(settings.get("resilience")),
                               meter=meter, emit=emit)
        return cls(mode=mode, role=role, meter=meter, knowledge=knowledge,
                   llm_trigger=settings.get("llm_trigger"),
                   max_llm_attempts=settings.get("max_llm_attempts", 2), emit=emit)

    # -- review --------------------------------------------------------------

    def review(self, snapshot, observation, action):
        """The verdict on ``action`` given ``snapshot`` (``Ledger.snapshot()``)."""
        started = time.monotonic()
        mark = len(self.meter.records)
        _guard(observation)
        self.docks.update(observed_docks(snapshot))
        if not isinstance(action, dict) or not isinstance(action.get("action"), str):
            return self._finish(Verdict("pass", [], [], [], None, None,
                                        "no action object to review", "none", {},
                                        mode=self.mode), mark, started, counted=False)
        rules = self.rules.check(snapshot, observation, action) if self.mode != "llm" else None
        inv = inventory(snapshot, observation)
        trigger = [] if action["action"] == "finish" else self._trigger(rules, snapshot, action)
        llm = None
        if trigger and self.llm is not None:
            llm = self.llm.review(snapshot, observation, action, inv,
                                  passthrough=(BudgetExhausted,))
        verdict = self._merge(snapshot, observation, action, rules, llm, inv)
        verdict.trigger = trigger
        verdict.llm_triggered = bool(trigger) and self.llm is not None
        verdict.rules = rules.record() if rules is not None else None
        verdict.llm = llm.record() if llm is not None else None
        return self._finish(verdict, mark, started, counted=True, action=action)

    def recheck(self, snapshot, observation, action):
        """Problems with a replacement action: infeasible, or a hard rule finding."""
        self.docks.update(observed_docks(snapshot))
        problems = feasible(action, snapshot, observation, docks=self.docks)
        if not problems and self.mode != "llm":
            result = self.rules.check(snapshot, observation, action)
            problems = [f"{f.rule}: {f.message}" for f in result.hard]
        return problems

    def _trigger(self, rules, snapshot, action):
        if self.llm is None:
            return []
        if self.mode == "llm" or self.llm_trigger == "always":
            return ["every action is reviewed"]
        reasons = outside_card_triggers(snapshot, action)
        if rules.soft:
            reasons.append("soft rule finding: " + ", ".join(sorted({f.rule for f in rules.soft})))
        if rules.undecided:
            reasons.append("rules undecided: " + "; ".join(
                f"{u['rule']} ({u['why']})" for u in rules.undecided[:3]))
        if rules.consequential and rules.hazard:
            reasons.append("hazardous families involved: " + ", ".join(rules.hazard))
        return reasons

    def _accept(self, candidates, original, snapshot, observation):
        """The first ``(source, action)`` candidate that is allowed, feasible and rule-clean."""
        rejected = []
        for source, candidate in candidates:
            if not isinstance(candidate, dict) or candidate == original:
                rejected.append({"source": source, "rewrite": candidate,
                                 "problems": ["same as the proposal"]})
                continue
            problems = (rewrite_kind_problems(candidate, original, snapshot, observation)
                        if source == "llm" else [])
            problems = problems or self.recheck(snapshot, observation, candidate)
            if not problems:
                return candidate, rejected
            rejected.append({"source": source, "rewrite": candidate, "problems": problems})
        return None, rejected

    def _merge(self, snapshot, observation, action, rules, llm, inv):
        answer = llm.answer if llm is not None and llm.status == "verified" else None
        llm_rejects = answer is not None and answer["decision"] in ("block", "rewrite")
        llm_rewrite = [answer["rewrite"]] if answer and answer["decision"] == "rewrite" else []
        rule_ids = rules.rule_ids if rules is not None else []
        verdict = Verdict("pass", rule_ids, [], [], None, None, "", "rules", {}, mode=self.mode)

        if rules is not None and rules.hard:
            verdict.decision = "block"
            verdict.basis = "rules"
            verdict.reason = " ".join(f.message for f in rules.hard)
            verdict.card_ids = rules.card_ids
            verdict.evidence = rules.evidence
            verdict.confidence = 1.0
            verdict.risk_category = RISK_BY_RULE[rules.hard[0].rule]
            verdict.channel = "rules+llm" if llm_rejects else "rules"
            candidates = [("rules", f.rewrite) for f in rules.hard if f.rewrite]
            candidates += [("llm", r) for r in llm_rewrite]
        elif llm_rejects:
            verdict.decision = "block"
            verdict.reason = answer["reason"]
            verdict.card_ids = answer["card_ids"]
            verdict.evidence = answer["evidence"]
            verdict.confidence = answer["confidence"]
            verdict.risk_category = answer["risk_category"]
            verdict.basis = answer.get("basis")
            verdict.channel = "llm-uncarded" if verdict.basis == "uncarded" else "llm"
            candidates = [("llm", r) for r in llm_rewrite]
        else:
            candidates = []
            if answer is not None:
                verdict.channel = "llm"
                verdict.reason = answer["reason"]
                verdict.confidence = answer["confidence"]
                verdict.card_ids = answer["card_ids"]
                verdict.evidence = answer["evidence"]
                verdict.risk_category = "none"
            else:
                verdict.channel = "llm" if self.mode == "llm" else "rules"
                verdict.reason = self._pass_reason(rules, llm)
            if rules is not None and rules.soft:
                verdict.card_ids = list(dict.fromkeys(verdict.card_ids + rules.card_ids))

        if verdict.decision == "block" and candidates:
            chosen, verdict.rewrite_rejected = self._accept(candidates, action, snapshot,
                                                            observation)
            if chosen is not None:
                verdict.decision, verdict.rewrite = "rewrite", chosen
        if verdict.decision == "block":
            verdict.feedback = (f"SafeLab's reviewer did not pass on "
                                f"{json.dumps(action, ensure_ascii=False)}: {verdict.reason} "
                                f"{describe_inventory(inv)}")
            suggested = [r for r in verdict.rewrite_rejected
                         if r.get("source") == "llm" and isinstance(r.get("rewrite"), dict)]
            if suggested:
                verdict.feedback += (" The reviewer suggested "
                                     f"{json.dumps(suggested[0]['rewrite'], ensure_ascii=False)}"
                                     f"; it was not carried out "
                                     f"({suggested[0]['problems'][0]}).")
        elif verdict.decision == "rewrite":
            verdict.feedback = (f"SafeLab's reviewer replaced "
                                f"{json.dumps(action, ensure_ascii=False)} with "
                                f"{json.dumps(verdict.rewrite, ensure_ascii=False)} before it "
                                f"was carried out: {verdict.reason}")
        verdict.disagreement = self._disagreement(rules, answer, action)
        return verdict

    @staticmethod
    def _pass_reason(rules, llm):
        parts = []
        if rules is None:
            parts.append("no rule channel in this mode")
        elif rules.soft:
            parts.append("soft rule findings only (" + "; ".join(f.message for f in rules.soft)
                         + "), not enough to block on their own")
        elif rules.undecided:
            parts.append("the rules could not decide (" + "; ".join(
                u["why"] for u in rules.undecided[:3]) + ")")
        else:
            parts.append("no rule finding")
        if llm is not None:
            parts.append(f"the LLM verdict was {llm.status} and not used")
        return "; ".join(parts)+"."

    def _disagreement(self, rules, answer, action):
        if rules is None or answer is None:
            return None
        if rules.hard:
            rules_view = "block"
        elif rules.status == "clear":
            rules_view = "pass"
        else:
            return None
        llm_view = "block" if answer["decision"] in ("block", "rewrite") else "pass"
        if rules_view == llm_view:
            return None
        return {"rules": rules_view, "llm": llm_view, "action": action,
                "rule_ids": rules.rule_ids, "rule_reason": " ".join(f.message for f in rules.hard),
                "llm_decision": answer["decision"], "llm_card_ids": answer["card_ids"],
                "llm_reason": answer["reason"]}

    def _finish(self, verdict, mark, started, *, counted, action=None):
        records = self.meter.records[mark:]
        tokens = {}
        for record in records:
            for name, value in record["usage"].items():
                tokens[name] = tokens.get(name, 0)+value
        costs = [r["cost_usd"] for r in records if r["cost_usd"] is not None]
        actual = [r.get("actual_cost_usd") for r in records
                  if r.get("actual_cost_usd") is not None]
        hits = [r["cache_hit_tokens"] for r in records if r.get("cache_hit_tokens") is not None]
        verdict.usage = {**tokens, "llm_calls": len(records),
                         "cost_usd": round(sum(costs), 8) if costs else (0. if not records
                                                                         else None),
                         "cache_hit_tokens": sum(hits) if hits else None,
                         "actual_cost_usd": round(sum(actual), 8) if actual
                         else (0. if not records else None),
                         "llm_latency_s": round(sum(r["latency_s"] or 0. for r in records), 3),
                         "latency_s": round(time.monotonic()-started, 3)}
        if counted:
            counts = self.counts
            counts["reviews"] += 1
            counts["llm_triggered"] += int(verdict.llm_triggered)
            counts["llm_calls"] += len(records)
            counts["llm_tokens"] += sum(tokens.get(k, 0) for k in ("input_tokens",
                                                                   "output_tokens"))
            counts["llm_cache_hit_tokens"] += verdict.usage["cache_hit_tokens"] or 0
            counts["llm_cost_usd"] = round(counts["llm_cost_usd"]
                                           + (verdict.usage["cost_usd"] or 0.), 8)
            counts["llm_actual_cost_usd"] = round(counts["llm_actual_cost_usd"]
                                                  + (verdict.usage["actual_cost_usd"] or 0.), 8)
            counts["llm_latency_s"] = round(counts["llm_latency_s"]
                                            + verdict.usage["llm_latency_s"], 3)
            status = (verdict.llm or {}).get("status")
            if status:
                key = {"verified": "llm_verified", "unverified": "llm_unverified"}.get(
                    status, "llm_errors")
                counts[key] += 1
            counts[verdict.decision] += 1
            if verdict.disagreement:
                counts["disagreements"] += 1
                self.emit("disagreement", **verdict.disagreement)
        return verdict

    def stats(self):
        """Trigger ratio and token figures over every review so far (S2.5)."""
        counts = dict(self.counts)
        reviews, triggered = counts["reviews"], counts["llm_triggered"]
        mean = counts["llm_tokens"]/triggered if triggered else None
        skipped = reviews-triggered if self.llm is not None else 0
        calls = counts["llm_calls"]
        per_call = {
            "mean_llm_cost_usd": round(counts["llm_cost_usd"]/calls, 8) if calls else None,
            "mean_llm_actual_cost_usd": (round(counts["llm_actual_cost_usd"]/calls, 8)
                                         if calls else None),
            "mean_llm_latency_s": round(counts["llm_latency_s"]/calls, 3) if calls else None}
        return {**counts, **per_call, "mode": self.mode, "llm_trigger": self.llm_trigger,
                "trigger_ratio": round(triggered/reviews, 4) if reviews else None,
                "mean_tokens_per_triggered_review": round(mean, 1) if mean else None,
                "skipped_reviews": skipped,
                "estimated_tokens_saved": round(mean*skipped) if mean else None,
                "model": self.llm.model if self.llm else None}

    def record(self):
        return {"mode": self.mode, "llm_trigger": self.llm_trigger,
                "cards": len(self.knowledge.cards),
                "model": self.llm.model if self.llm else None,
                "max_llm_attempts": self.llm.max_attempts if self.llm else None}


# -- config helpers ------------------------------------------------------------


def _parse_config(config):
    if not isinstance(config, dict):
        raise ValueError("a critic config must be a dict or a path to a JSON file")
    backend = config.get("backend") if isinstance(config.get("backend"), dict) else None
    if backend is None and "roles" in config:
        backend = config
    if backend is not None and backend.get("provider") == "safelab":
        settings = dict(backend.get("critic") or {})
        model = (backend.get("roles") or {}).get("critic")
        pricing = {**(config.get("pricing_overrides") or {}), **(backend.get("pricing") or {})}
    elif backend is not None:
        settings = dict(config.get("critic") or {})
        model = backend
        pricing = dict(config.get("pricing_overrides") or {})
    else:
        settings = dict(config)
        model = config.get("model") if isinstance(config.get("model"), dict) else None
        pricing = dict(config.get("pricing") or {})
    if isinstance(settings.get("model"), dict):
        model = settings["model"]
    pricing.update(settings.get("pricing") or {})
    return settings, model, pricing


def _price_function(pricing):
    try:
        from agent_interface.pricing import price_for
    except ImportError:
        def local(model):
            row = (pricing or {}).get(model)
            if not row:
                return None
            # Without the platform's table, unpublished cache prices default to the
            # input price: an upper bound, never an underestimate.
            return {"input": row["input"], "output": row["output"],
                    "cache_read": row.get("cache_read", row["input"]),
                    "cache_write": row.get("cache_write", row["input"])}
        return local
    return lambda model: price_for(model, pricing)[0]


def _build_backend(spec):
    """A model backend for the critic (needs the platform)."""
    import os

    from .. import bench
    bench.ensure_importable()
    variable = spec.get("api_key_env")
    key = os.environ.get(variable) if variable else None
    if variable and not key:
        raise ValueError(f"critic model: environment variable {variable} is not set")
    if spec.get("provider") in ("openai_compatible", REASONING_PROVIDER):
        from ..openai_reasoning import ReasoningOpenAIBackend
        return ReasoningOpenAIBackend(spec, api_key=key)
    from agent_interface.backends import create_backend
    return create_backend(spec, api_key=key)

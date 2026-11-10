"""SafeLabBackend: the platform's Backend protocol, with SafeLab inside it.

The platform's episode loop calls ``generate(system=..., messages=...)`` once
per turn and expects one reply whose text ends in one JSON action. SafeLab
answers that call with its own internal round and returns a single
platform-format reply, so the loop, the logs and the evaluator are the same
for every experimental condition.

One turn of condition B:

1. parse the observation out of the platform's message and re-check it with
   the platform's own ``assert_no_evaluator_state``;
2. update the execution ledger from that readback (``executed`` and
   ``observed`` in the trace);
3. charge the reported action to the current stage, and let the reflexion
   module classify any failure the platform reported;
4. planner: on the first turn, write the stage plan; afterwards mark stages
   whose expected observations now hold as done, and replan on a mismatch, on
   two consecutive refusals, or on the second refusal of the same kind;
5. actor: propose one action for the current stage (``proposed``). An empty
   reply is retried at once. If the actor proposes ``finish`` while the
   plan's expected observations do not hold, the planner revises the plan
   once and the actor is asked again;
6. return the actor's reply (``returned``), with the token usage of every
   sub-call made this turn, so the platform's cost ceiling is a true bound.

If SafeLab's own budget would be passed, the turn returns ``finish`` with the
reason instead; if a sub-backend keeps failing after retries, the platform
gets a ``BackendError``. Sub-backends are created from the ``roles`` block of
the spec; each reads its key from the environment variable its own
``api_key_env`` names, never from a file.

Condition C adds the safety critic (``safelab.critic``) between steps 5 and 6.
Every proposal is reviewed (``reviewed``); a ``pass`` is returned as is, a
``rewrite`` returns the critic's replacement (feasible now and re-checked by
the rules) and tells the actor on the next turn what was replaced and why, and
a ``block`` goes back to the actor with the critic's reason. Within one turn
the first block asks the actor again, the second revises the plan first, and
a third ends the episode with ``finish`` and the reason (safe stop). Across
turns, the refusals of each action (same name and string parameters, see
``reflexion.action_key``) are counted for the whole run; the
``critic.max_repeat_rejections``-th refusal of the same action (default 3)
also ends the episode safely, with a ``refusal_limit`` event in the trace. The
actor's and planner's own prompts are the same as in B; the critic's reason
reaches them only as feedback on a refused proposal.

This module imports the platform, so it is only importable after
``safelab.bench.ensure_importable()``.
"""
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path

from agent_interface.action_schema import available_actions
from agent_interface.backends import BackendError, BackendRefusal, BackendReply, create_backend
from agent_interface.observation import assert_no_evaluator_state
from agent_interface.parsing import extract_action
from agent_interface.pricing import price_for

from .actor import Actor, build_message
from .critic import Critic
from .critic.knowledge import KnowledgeError
from .ledger import Ledger, format_diff
from .obs import ObservationParseError, parse_step_message
from .planner import Planner, PlanTracker
from .reflexion import BRIEF_ENV, ReflectionLibrary, Reflexion, lesson_text
from .resilience import (
    Budget,
    BudgetExhausted,
    FaultInjector,
    GuardedRole,
    RetriesExhausted,
    RetryPolicy,
    UsageMeter,
)
from .trace import TraceLog

#: Conditions this build can run.
SUPPORTED_CONDITIONS = ("B", "C")
ROLES = ("planner", "actor", "critic")
REASONING_PROVIDER = "openai_compatible_reasoning"
REPO = Path(__file__).resolve().parents[2]
NOTES = {
    "B": ("Condition B: stage planner, actor, readback-only execution ledger, failure "
          "reflexion and resilient sub-calls. No critic."),
    "C": ("Condition C: condition B plus the safety critic (rule channel R1-R6 over the "
          "ledger, LLM channel with evidence check, gate with a per-step rejection limit)."),
}
#: Provider errors that a retry cannot fix.
_PERMANENT_ERRORS = ("AuthenticationError", "PermissionDeniedError", "BadRequestError",
                     "NotFoundError", "UnprocessableEntityError")


def _role_key(role, spec):
    variable = spec.get("api_key_env")
    if not variable:
        return None
    key = os.environ.get(variable)
    if not key:
        raise BackendError(f"SafeLab role {role!r}: environment variable {variable} is not set")
    return key


def _retryable(exc):
    if isinstance(exc, BackendRefusal):
        return False
    if isinstance(exc, BackendError):
        return not any(name in str(exc) for name in _PERMANENT_ERRORS)
    return isinstance(exc, (TimeoutError, ConnectionError))


def _make_reply(text, model):
    return BackendReply(text=text, model=model, stop_reason="injected_garbled", latency_s=0.)


def _library_path(value):
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPO/path


class SafeLabBackend:
    provider = "safelab"

    def __init__(self, spec, *, api_key=None, context=None, run_dir=None, brief=None,
                 sleep=time.sleep):
        self.spec = deepcopy(spec)
        self.condition = spec.get("condition", "B")
        if self.condition not in SUPPORTED_CONDITIONS:
            raise BackendError(
                f"SafeLab condition {self.condition!r} is not available in this build "
                f"(supported: {', '.join(SUPPORTED_CONDITIONS)})")
        roles = spec.get("roles")
        if not isinstance(roles, dict) or not isinstance(roles.get("actor"), dict):
            raise BackendError("A safelab backend needs roles.actor naming a sub-backend")
        unknown = sorted(set(roles)-set(ROLES))
        if unknown:
            raise BackendError(f"Roles not implemented in this build: {unknown}")
        if "critic" in roles and self.condition != "C":
            raise BackendError("roles.critic belongs to condition C")
        critic_settings = spec.get("critic") or {}

        self.events = TraceLog.for_run(run_dir)
        pricing = spec.get("pricing") or {}
        self.meter = UsageMeter(price_for=lambda model: price_for(model, pricing)[0])
        resilience = spec.get("resilience") or {}
        self.policy = RetryPolicy.from_spec(resilience)
        self.budget = Budget(resilience.get("budget_usd"), self.meter,
                             min_reserve_usd=resilience.get("min_reserve_usd", 0.))
        self.faults = FaultInjector(resilience.get("faults"))
        # The platform resolves one key for the top-level backend; sub-roles
        # resolve their own, so the top-level ``api_key`` is not used.
        self.roles = {name: GuardedRole(
            name, self._build_role(name, roles[name], context), policy=self.policy,
            meter=self.meter, budget=self.budget, faults=self.faults,
            is_retryable=_retryable, make_reply=_make_reply, emit=self.events.emit, sleep=sleep)
            for name in ROLES if name in roles}
        self.model = spec.get("model") or self.roles["actor"].model

        planner = spec.get("planner") or {}
        self.planner_mode = planner.get("mode", "model" if "planner" in self.roles else "fixed")
        if self.planner_mode not in ("model", "fixed"):
            raise BackendError("planner.mode must be 'model' or 'fixed'")
        if self.planner_mode == "model" and "planner" not in self.roles:
            raise BackendError("planner.mode 'model' needs roles.planner")
        self.check_finish = bool(planner.get("check_finish", True))
        self.tracker = PlanTracker(max_replans=planner.get("max_replans", 3))
        self.planner = Planner(self.roles.get("planner") if self.planner_mode == "model" else None,
                               action_names=available_actions(),
                               max_empty_retries=planner.get("max_empty_retries", 2),
                               emit=self.events.emit)
        actor = spec.get("actor") or {}
        self.k = int(actor.get("history_k", 6))
        self.actor = Actor(self.roles["actor"], parse_action=extract_action, k=self.k,
                           max_empty_retries=actor.get("max_empty_retries", 2),
                           emit=self.events.emit)
        reflexion = spec.get("reflexion") or {}
        self.reflexion = Reflexion(consecutive_limit=reflexion.get("consecutive_failures", 2),
                                   same_kind_limit=reflexion.get("same_kind_failures", 2),
                                   critic_limit=critic_settings.get("max_rejections", 2),
                                   repeat_limit=critic_settings.get("max_repeat_rejections", 3))
        self.critic = None
        if self.condition == "C":
            mode = critic_settings.get("mode", "dual")
            if mode != "rules" and "critic" not in self.roles:
                raise BackendError(f"critic mode {mode!r} needs roles.critic")
            try:
                self.critic = Critic(mode=mode, role=self.roles.get("critic"), meter=self.meter,
                                     llm_trigger=critic_settings.get("llm_trigger"),
                                     max_llm_attempts=critic_settings.get("max_llm_attempts", 2),
                                     emit=self.events.emit)
            except (ValueError, KnowledgeError) as exc:
                raise BackendError(f"SafeLab critic: {exc}") from exc
        #: The critic's note on a replaced action, shown to the actor on the next turn.
        self.critic_note = None
        self.brief = brief or os.environ.get(BRIEF_ENV)
        self.library = ReflectionLibrary(_library_path(reflexion.get("library")),
                                         brief=self.brief)
        self.notes = []

        self.ledger = Ledger()
        self.calls = 0
        self.finish_replans = 0
        self.last_fragment = None
        self.ended = False
        #: One entry per call, in memory: what the ledger saw and what was returned.
        self.trace = []

    # -- construction --------------------------------------------------------

    @staticmethod
    def _build_role(name, spec, context):
        if not isinstance(spec, dict) or not spec.get("provider"):
            raise BackendError(f"roles.{name} must name a sub-backend provider")
        if spec["provider"] == SafeLabBackend.provider:
            raise BackendError(f"roles.{name} must name a platform provider other than 'safelab'")
        key = _role_key(name, spec)
        if spec["provider"] == REASONING_PROVIDER:
            from .openai_reasoning import ReasoningOpenAIBackend
            return ReasoningOpenAIBackend(spec, api_key=key)
        return create_backend(spec, api_key=key, context=context)

    # -- one platform turn ---------------------------------------------------

    def generate(self, *, system, messages):
        started = time.monotonic()
        self.calls += 1
        mark = len(self.meter.records)
        if not messages:
            raise BackendError("SafeLab received no messages")
        try:
            message = parse_step_message(messages[-1]["content"])
        except (ObservationParseError, KeyError, TypeError) as exc:
            raise BackendError(f"SafeLab could not read the observation: {exc}") from exc
        assert_no_evaluator_state(message.observation)
        observation = message.observation
        try:
            changes = self.ledger.update(observation)
        except ValueError as exc:
            raise BackendError(f"SafeLab could not use the observation: {exc}") from exc
        self.events.bind(call=self.calls, step=observation.get("step_index"))
        if self.calls == 1:
            self._start()
        self._log_readback(message, changes)

        last = self.ledger.last_action
        self.tracker.record_outcome((last or {}).get("status"))
        assessment = self.reflexion.assess(message.feedback_kind, message.feedback, last)
        if assessment is not None:
            self.events.emit("reflect", **assessment.record())

        try:
            proposal, strategy = self._decide(system, message, assessment)
            outcome = self._review(system, message, proposal, strategy)
        except BudgetExhausted as exc:
            return self._safe_stop(str(exc), mark, started, changes)
        except RetriesExhausted as exc:
            self.events.emit("reflect", **self.reflexion.api_error(str(exc)).record())
            raise BackendError(f"SafeLab {exc}") from exc
        if outcome["stop"] is not None:
            return self._safe_stop(outcome["stop"], mark, started, changes,
                                   source="safelab_critic_stop", verdicts=outcome["verdicts"])

        proposal, strategy, action = outcome["proposal"], outcome["strategy"], outcome["action"]
        if isinstance(action, dict) and action.get("action") != "finish":
            self.ledger.expect(action)
        self.last_fragment = outcome["fragment"]
        reply = proposal.reply
        self.events.emit("returned", action=deepcopy(action), source=outcome["source"],
                         stage=self.tracker.stage_record())
        self.trace.append({"call": self.calls, "step_index": observation.get("step_index"),
                           "feedback_kind": message.feedback_kind, "ledger_changes": changes,
                           "ledger": self.ledger.snapshot(),
                           "actor_action": deepcopy(proposal.action),
                           "returned_action": deepcopy(action), "source": outcome["source"],
                           "critic": [v.decision for v in outcome["verdicts"]],
                           "strategy": strategy})
        annotation = self._annotation(changes, strategy, proposal.empty_retries, mark,
                                      reply.model, verdicts=outcome["verdicts"])
        rewritten = outcome["source"] == "critic_rewrite"
        return BackendReply(
            text=outcome["text"], model=self.model,
            stop_reason="safelab_critic_rewrite" if rewritten else reply.stop_reason,
            stop_details=None if rewritten else reply.stop_details,
            usage=self.meter.usage_since(mark),
            latency_s=time.monotonic()-started, thinking=reply.thinking,
            provider_request_id=reply.provider_request_id, extra={"safelab": annotation})

    def _decide(self, system, message, assessment):
        observation = message.observation
        snapshot = self.ledger.snapshot()
        strategy = assessment.strategy if assessment else None
        if self.tracker.version == 0:
            self._plan(system, snapshot, observation)
        else:
            for name in self.tracker.advance(snapshot):
                self.events.emit("stage", status="done", name=name)
            reason = None
            if strategy == "replan":
                reason = (f"{assessment.consecutive_failures} consecutive refused action(s), "
                          f"{assessment.same_kind} of this kind; last error: {assessment.detail}")
            else:
                mismatch = self.tracker.mismatch(snapshot)
                if mismatch:
                    self.events.emit("reflect", **self.reflexion.mismatch(mismatch).record())
                    reason = mismatch
            if reason is not None:
                strategy = "replan" if self._replan(system, snapshot, observation, reason) \
                    else ("remediate" if strategy == "replan" else strategy)
        self._sync_stage()
        proposal = self._propose(system, message, strategy)

        action = proposal.action or {}
        if action.get("action") == "finish" and self.check_finish and self.finish_replans < 1:
            unmet = self.tracker.unmet(self.ledger.snapshot())
            if unmet and self.tracker.can_replan():
                self.finish_replans += 1
                detail = ("finish was proposed while these expected observations do not "
                          "hold: " + "; ".join(unmet))
                self.events.emit("reflect", **self.reflexion.mismatch(detail).record())
                if self._replan(system, self.ledger.snapshot(), observation, detail):
                    strategy = "replan"
                    self._sync_stage()
                    proposal = self._propose(system, message, strategy)
        return proposal, strategy

    # -- planning ------------------------------------------------------------

    def _plan(self, system, snapshot, observation):
        result = self.planner.make(system, snapshot, observation, notes=self.notes, version=1)
        if result.stages:
            self.tracker.adopt(result.stages, source="model")
        else:
            self.tracker.adopt_fallback()
        done = self.tracker.advance(snapshot)
        self.events.emit("plan", source=self.tracker.source, version=self.tracker.version,
                         stages=self._stages(), errors=result.errors,
                         empty_replies=result.empty_replies, done_on_adoption=done,
                         replies=[self._reply_record(r) for r in result.replies])

    def _replan(self, system, snapshot, observation, reason, *, keep_critic=False):
        """Revise the plan; return whether a model replan happened."""
        if not self.tracker.can_replan():
            if not self.tracker.fallback:
                self.tracker.adopt_fallback(after_actions=len(self.ledger.actions))
                self.events.emit("replan", source="fallback", version=self.tracker.version,
                                 reason=reason, note="the replan allowance is used up",
                                 stages=self._stages())
            return False
        self.tracker.replans += 1
        result = self.planner.make(system, snapshot, observation, notes=self.notes,
                                   reason=reason, tracker=self.tracker,
                                   version=self.tracker.version+1)
        if result.stages:
            self.tracker.adopt(result.stages, source="model")
        else:
            self.tracker.adopt_fallback(after_actions=len(self.ledger.actions))
        self.reflexion.replanned(keep_critic=keep_critic)
        done = self.tracker.advance(snapshot)
        self.events.emit("replan", source=self.tracker.source, version=self.tracker.version,
                         reason=reason, replans=self.tracker.replans, stages=self._stages(),
                         errors=result.errors, done_on_adoption=done,
                         replies=[self._reply_record(r) for r in result.replies])
        return result.stages is not None

    def _sync_stage(self):
        record = self.tracker.stage_record()
        previous = self.ledger.stage
        self.ledger.set_stage(record)
        if previous != record:
            self.events.emit("stage", status="current", **record)

    def _stages(self):
        return [{"name": s.name, "subgoal": s.subgoal, "preconditions": s.preconditions,
                 "expected": s.expected, "max_actions": s.max_actions, "status": s.status}
                for s in self.tracker.stages if s.plan_version == self.tracker.version
                or s.status == "done"]

    # -- acting --------------------------------------------------------------

    def _propose(self, system, message, strategy, critic_feedback=None):
        snapshot = self.ledger.snapshot()
        entity_ids = {*snapshot["containers"], *snapshot["tips"], *snapshot["devices"]}
        if critic_feedback is None and self.critic_note:
            critic_feedback, self.critic_note = self.critic_note, None
        feedback = "\n".join(part for part in (message.feedback, critic_feedback) if part) \
            or None
        text = build_message(
            plan_text=self.tracker.render(snapshot), snapshot=snapshot,
            observation=message.observation, focus=self.tracker.focus(entity_ids),
            feedback=feedback, strategy=strategy,
            previous_fragment=self.last_fragment if message.feedback_kind == "invalid_reply"
            else None, k=self.k)
        proposal = self.actor.propose(system=system, message=text)
        for _ in range(proposal.empty_retries):
            self.events.emit("reflect", **self.reflexion.empty_reply("actor").record())
        self.events.emit("proposed", action=deepcopy(proposal.action),
                         fragment=proposal.fragment, parse_error=proposal.parse_error,
                         empty_retries=proposal.empty_retries, strategy=strategy,
                         stage=self.tracker.stage_record(), prompt=text,
                         reply=self._reply_record(proposal.reply))
        return proposal

    # -- reviewing (condition C) ---------------------------------------------

    def _review(self, system, message, proposal, strategy):
        """Put each proposal to the critic until one is passed, rewritten, or the step stops."""
        out = {"proposal": proposal, "strategy": strategy, "action": proposal.action,
               "text": proposal.reply.text, "fragment": proposal.fragment, "source": "actor",
               "verdicts": [], "stop": None}
        if self.critic is None:
            return out
        self.reflexion.critic_passed()          # the limit counts refusals within one step
        for _ in range(2*self.reflexion.critic_limit+2):
            action = proposal.action
            out.update(proposal=proposal, strategy=strategy, action=action,
                       text=proposal.reply.text, fragment=proposal.fragment, source="actor")
            if not isinstance(action, dict):
                return out                      # unreadable: the platform reports it
            verdict = self.critic.review(self.ledger.snapshot(), message.observation, action)
            out["verdicts"].append(verdict)
            self.events.emit("reviewed", proposed=deepcopy(action),
                             attempt=len(out["verdicts"]), **verdict.record())
            if verdict.decision == "pass":
                self.reflexion.critic_passed()
                return out
            if verdict.decision == "rewrite":
                self.reflexion.critic_passed()
                self.critic_note = verdict.feedback
                text = json.dumps(verdict.rewrite, ensure_ascii=False)
                out.update(action=deepcopy(verdict.rewrite), text=f"```json\n{text}\n```",
                           fragment=text, source="critic_rewrite")
                return out
            assessment = self.reflexion.critic_rejection(verdict.reason, action)
            self.events.emit("reflect", **assessment.record())
            if assessment.strategy == "safe_terminate":
                if self.reflexion.critic_rejections > self.reflexion.critic_limit:
                    out["stop"] = (f"its reviewer refused {len(out['verdicts'])} proposals for "
                                   f"this step; the last reason: {verdict.reason}")
                    return out
                # Not the per-step limit: the cross-turn count of this action ended the run.
                self.events.emit("refusal_limit", action=deepcopy(action),
                                 key=assessment.signature, repeats=assessment.repeats,
                                 limit=self.reflexion.repeat_limit, reason=verdict.reason,
                                 refused=dict(self.reflexion.refused))
                out["stop"] = (f"its reviewer refused the same action ({assessment.signature}) "
                               f"{assessment.repeats} times in this run; the last reason: "
                               f"{verdict.reason}")
                return out
            if assessment.strategy == "replan":
                reason = (f"SafeLab's reviewer refused {assessment.same_kind} proposals in a row "
                          f"for this step; the last reason: {verdict.reason}")
                self._replan(system, self.ledger.snapshot(), message.observation, reason,
                             keep_critic=True)
                self._sync_stage()
            strategy = assessment.strategy
            feedback = verdict.feedback
            if self.reflexion.repeat_limit and assessment.repeats:
                feedback += (f" This action has been refused {assessment.repeats} time(s) in "
                             f"this run; at {self.reflexion.repeat_limit} the run ends.")
            proposal = self._propose(system, message, strategy, critic_feedback=feedback)
        out["stop"] = "its reviewer kept refusing the proposals for this step"
        return out

    def _safe_stop(self, reason, mark, started, changes, *, source="safelab_budget_stop",
                   verdicts=()):
        if source == "safelab_budget_stop":
            self.events.emit("reflect", **self.reflexion.budget(reason).record())
            self.events.emit("budget_stop", reason=reason, spent_usd=self.meter.spent_usd,
                             budget_usd=self.budget.limit_usd)
            text = f"SafeLab stopped to stay within its budget: {reason}"
        else:
            text = f"SafeLab stopped safely: {reason}"
        action = {"action": "finish", "reason": text}
        self.events.emit("returned", action=action, source=source,
                         stage=self.tracker.stage_record())
        self.trace.append({"call": self.calls, "step_index": self.ledger.step_index,
                           "feedback_kind": None, "ledger_changes": changes,
                           "ledger": self.ledger.snapshot(), "actor_action": action,
                           "returned_action": action, "source": source,
                           "critic": [v.decision for v in verdicts],
                           "strategy": "safe_terminate"})
        text = "```json\n"+json.dumps(action, ensure_ascii=False)+"\n```"
        return BackendReply(text=text, model=self.model, stop_reason=source,
                            usage=self.meter.usage_since(mark),
                            latency_s=time.monotonic()-started,
                            extra={"safelab": self._annotation(changes, "safe_terminate", 0,
                                                               mark, None, verdicts=verdicts)})

    # -- records -------------------------------------------------------------

    @staticmethod
    def _reply_record(reply):
        return {"text": getattr(reply, "text", None),
                "reasoning": getattr(reply, "thinking", None),
                "model": getattr(reply, "model", None),
                "stop_reason": getattr(reply, "stop_reason", None),
                "usage": getattr(reply, "usage", None),
                "usage_detail": (getattr(reply, "extra", None) or {}).get("usage_detail"),
                "provider_request_id": getattr(reply, "provider_request_id", None)}

    def _annotation(self, changes, strategy, empty_retries, mark, actor_model, verdicts=()):
        turn = self.meter.records[mark:]
        costs = [r["cost_usd"] for r in turn if r["cost_usd"] is not None]
        critic = None
        if self.critic is not None:
            critic = [{"decision": v.decision, "rule_ids": v.rule_ids, "card_ids": v.card_ids,
                       "channel": v.channel, "llm_triggered": v.llm_triggered,
                       "rewrite": v.rewrite} for v in verdicts]
        return {"condition": self.condition, "stage": self.tracker.stage_record(),
                "critic": critic,
                "ledger_step_index": self.ledger.step_index,
                "ledger_change_count": len(changes),
                "ledger_diff": format_diff(changes) if self.calls > 1 else None,
                "unconfirmed_count": len(self.ledger.unconfirmed),
                "strategy": strategy, "actor_empty_retries": empty_retries,
                "sub_calls": [{"role": r["role"], "model": r["model"]} for r in turn],
                "turn_cost_usd": round(sum(costs), 8) if costs else None,
                "spent_usd": self.meter.spent_usd, "actor_model": actor_model,
                "trace": str(self.events.path) if self.events.path else None}

    def _start(self):
        entries = self.library.read()
        self.notes = [entry.get("text") or lesson_text(entry) for entry in entries]
        self.events.emit(
            "run_start", condition=self.condition, model=self.model,
            roles={name: role.record() for name, role in self.roles.items()},
            planner_mode=self.planner_mode, max_replans=self.tracker.max_replans,
            check_finish=self.check_finish, history_k=self.k, brief=self.brief,
            critic=self.critic.record() if self.critic else None,
            split=self.library.split, library=str(self.library.path) if self.library.path
            else None, policy=vars(self.policy), budget_usd=self.budget.limit_usd,
            faults_enabled=self.faults.enabled)
        self.events.emit("reflection_read", split=self.library.split,
                         entries=[entry.get("id") for entry in entries], count=len(entries))

    def _log_readback(self, message, changes):
        last = self.ledger.last_action
        if self.calls > 1 and last is not None:
            self.events.emit("executed", action_step=last["step"], action=last["action"],
                             status=last["status"], error=last["error"])
        self.events.emit("observed", feedback_kind=message.feedback_kind,
                         feedback=message.feedback,
                         changes=changes if self.calls > 1 else None,
                         change_count=len(changes),
                         ledger=self.ledger.snapshot() if self.calls == 1 else None,
                         unconfirmed=self.ledger.unconfirmed[-3:])

    def _end(self):
        self.ended = True
        lessons = self.reflexion.lessons(self.ledger.actions)
        written = self.library.write(lessons, run=str(self.events.path.parent)
                                     if self.events.path else None)
        self.events.emit("reflection_write", split=self.library.split,
                         writable=self.library.writable, candidates=len(lessons),
                         written=[row["id"] for row in written],
                         blocked=bool(lessons) and not self.library.writable)
        self.events.emit("run_end", calls=self.calls, usage=self.meter.report(),
                         plan=self.tracker.record(), unconfirmed=len(self.ledger.unconfirmed),
                         assessments=[a.record() for a in self.reflexion.history],
                         critic=self.critic.stats() if self.critic else None,
                         refused=dict(self.reflexion.refused) if self.critic else None)

    def record(self):
        if self.calls and not self.ended:
            self._end()
        roles = {name: role.record() for name, role in self.roles.items()}
        return {"provider": self.provider, "model": self.model, "condition": self.condition,
                "is_model": any(bool(r.get("is_model", True)) for r in roles.values()),
                "roles": roles,
                "components": {"ledger": "readback_only",
                               "planner": ("model_stage_plan" if self.planner_mode == "model"
                                           else "fixed_two_stage"),
                               "actor": "stage_conditioned",
                               "critic": (f"rules_llm_gate:{self.critic.mode}"
                                          if self.critic else "off_in_condition_B"),
                               "reflexion": "classify_and_recover",
                               "resilience": "retry_timeout_budget"},
                "run": {"brief": self.brief, "split": self.library.split,
                        "trace": str(self.events.path) if self.events.path else None},
                "plan": {"version": self.tracker.version, "source": self.tracker.source,
                         "replans": self.tracker.replans, "fallback": self.tracker.fallback},
                "usage_by_model": self.meter.report(),
                "settings": {"policy": vars(self.policy), "budget_usd": self.budget.limit_usd,
                             "faults_enabled": self.faults.enabled},
                "critic": ({**self.critic.record(), "stats": self.critic.stats()}
                           if self.critic else None),
                "note": NOTES[self.condition]}

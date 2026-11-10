"""Failure classification, recovery strategy, and the long-term reflection library.

Failure classes and strategies (execution plan S1.6, plus ``empty_reply``):

==================== ======================================= ===============================
kind                 recognised by                            strategy
==================== ======================================= ===============================
empty_reply          the actor or planner reply has no text   retry at once; not a format error
invalid_reply        platform: "That reply could not be used" self_correct with the error, once
precondition_failed  platform: "That action was not carried   remediate; replan at the 2nd
                     out" and the operation's own words       failure of the same kind or the
                                                              2nd consecutive failure
critic_rejected      SafeLab's critic (condition C)           rewrite; replan at the 2nd
                                                              rejection; then safe_terminate.
                                                              Across turns: the same action
                                                              (``action_key``) refused
                                                              ``repeat_limit`` times in the
                                                              run -> safe_terminate
expectation_mismatch the planner's expected observations      replan
api_error            the resilience layer ran out of retries  backend_error (to the platform)
budget_exhausted     SafeLab's own cost total                 safe_terminate (finish + reason)
==================== ======================================= ===============================

Long-term library. A JSONL file of factual entries, each with a ``split``.
Which split a run belongs to is fixed here, before any experiment: the
procedural briefs and ``suspension_dispensing`` are ``train``; the two
open-ended briefs are ``test``. Only a train run writes. Every run reads only
train entries and logs which ones it read. An entry records an action the
platform refused, its error, and what was carried out before the same action
succeeded; it is a statement of what happened, not advice.

No platform import.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FAILURE_KINDS = ("empty_reply", "invalid_reply", "precondition_failed", "critic_rejected",
                 "expectation_mismatch", "api_error", "budget_exhausted")
STRATEGIES = ("retry", "self_correct", "remediate", "rewrite", "replan", "safe_terminate",
              "backend_error")

#: Pre-registered train/test split, by brief (file name without ``.json``).
SPLITS = {
    "waste_segregation_v1": "train",
    "cell_lysis_normal_execution_v1": "train",
    "suspension_dispensing": "train",
    "waste_segregation_v1.open": "test",
    "cell_lysis_normal_execution_v1.open": "test",
}
UNASSIGNED = "unassigned"
#: Environment variable the launch scripts set to the brief's name.
BRIEF_ENV = "SAFELAB_BRIEF"


def split_for(brief):
    return SPLITS.get(brief or "", UNASSIGNED)


def action_key(action):
    """What makes two proposals "the same action" for the cross-turn refusal count.

    The action name and every string-valued parameter (target, receiver,
    device, support, tip_id, pipette_type, program, condition ...), but not the
    numbers (volume, duration, angle) and not a finish ``reason``: proposing a
    refused transfer again with another volume is still the same transfer.
    """
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        return None
    params = sorted((key, value) for key, value in action.items()
                    if key not in ("action", "reason") and isinstance(value, str))
    return " ".join([action["action"], *(f"{key}={value}" for key, value in params)])


def signature(action, error):
    """A failure's kind: the action name and its error with numbers removed."""
    name = (action or {}).get("action") or "?"
    text = re.sub(r"[-+]?\d+(\.\d+)?", "#", (error or "").strip())[:120]
    return f"{name}: {text}"


@dataclass
class Assessment:
    kind: str
    strategy: str
    detail: str | None = None
    signature: str | None = None
    consecutive_failures: int = 0
    same_kind: int = 0
    repeats: int | None = None      # critic_rejected: refusals of this action in the run

    def record(self):
        out = {"kind": self.kind, "strategy": self.strategy, "detail": self.detail,
               "signature": self.signature, "consecutive_failures": self.consecutive_failures,
               "same_kind": self.same_kind}
        if self.repeats is not None:
            out["repeats"] = self.repeats
        return out


class Reflexion:
    def __init__(self, *, consecutive_limit=2, same_kind_limit=2, critic_limit=2,
                 repeat_limit=3):
        self.consecutive_limit = int(consecutive_limit)
        self.same_kind_limit = int(same_kind_limit)
        self.critic_limit = int(critic_limit)
        #: Refusals of one action (``action_key``) over the whole run that end it; 0: off.
        self.repeat_limit = int(repeat_limit or 0)
        self.consecutive_failures = 0
        self.kind_counts = {}
        self.critic_rejections = 0
        #: action_key -> refusals in this run. Never reset: not by a pass, not by a replan.
        self.refused = {}
        self.failures = []            # (step, action, error) of refused actions
        self.history = []             # every Assessment, in order

    def _note(self, assessment):
        self.history.append(assessment)
        return assessment

    def assess(self, feedback_kind, feedback, last_action):
        """Classify the platform's feedback on the previous turn (None when there was none)."""
        status = (last_action or {}).get("status")
        if status == "complete":
            self.consecutive_failures = 0
            return None
        if feedback_kind == "invalid_reply" or status == "invalid_reply":
            return self._note(Assessment("invalid_reply", "self_correct", detail=feedback))
        if feedback_kind == "action_failed" or status == "failed":
            action = (last_action or {}).get("action")
            error = (last_action or {}).get("error") or feedback
            key = signature(action, error)
            self.consecutive_failures += 1
            self.kind_counts[key] = self.kind_counts.get(key, 0)+1
            self.failures.append(((last_action or {}).get("step"), action, error))
            replan = (self.consecutive_failures >= self.consecutive_limit
                      or self.kind_counts[key] >= self.same_kind_limit)
            return self._note(Assessment(
                "precondition_failed", "replan" if replan else "remediate", detail=error,
                signature=key, consecutive_failures=self.consecutive_failures,
                same_kind=self.kind_counts[key]))
        return None

    def empty_reply(self, role):
        return self._note(Assessment("empty_reply", "retry", detail=role))

    def mismatch(self, detail):
        return self._note(Assessment("expectation_mismatch", "replan", detail=detail))

    def critic_rejection(self, reason, action=None):
        """Condition C: the critic refused the proposed action.

        Within a step: rewrite, then replan, then safe_terminate. Across the run:
        the ``repeat_limit``-th refusal of the same action (``action_key``) is a
        safe_terminate whatever the step count says.
        """
        self.critic_rejections += 1
        key = action_key(action)
        repeats = None
        if key is not None:
            repeats = self.refused[key] = self.refused.get(key, 0)+1
        if self.repeat_limit and repeats is not None and repeats >= self.repeat_limit:
            strategy = "safe_terminate"
        elif self.critic_rejections > self.critic_limit:
            strategy = "safe_terminate"
        elif self.critic_rejections == self.critic_limit:
            strategy = "replan"
        else:
            strategy = "rewrite"
        return self._note(Assessment("critic_rejected", strategy, detail=reason, signature=key,
                                     same_kind=self.critic_rejections, repeats=repeats))

    def critic_passed(self):
        self.critic_rejections = 0

    def api_error(self, detail):
        return self._note(Assessment("api_error", "backend_error", detail=detail))

    def budget(self, detail):
        return self._note(Assessment("budget_exhausted", "safe_terminate", detail=detail))

    def replanned(self, *, keep_critic=False):
        """A new plan starts the failure counters afresh.

        ``keep_critic``: a replan the critic's second rejection caused keeps that
        count, so a further rejection of the same step ends it safely.
        """
        self.consecutive_failures = 0
        self.kind_counts = {}
        if not keep_critic:
            self.critic_rejections = 0

    def lessons(self, actions):
        """Refused actions that later succeeded, with what was carried out in between."""
        out = []
        seen = set()
        for step, action, error in self.failures:
            if not isinstance(action, dict) or step is None:
                continue
            name, target = action.get("action"), action.get("target")
            later = [row for row in actions if row.get("step") is not None
                     and row["step"] > step]
            success = next((row for row in later if row["status"] == "complete"
                            and row["action"].get("action") == name
                            and row["action"].get("target") == target), None)
            if success is None:
                continue
            between = [row["action"].get("action") for row in later
                       if row["status"] == "complete" and row["step"] < success["step"]]
            key = (name, target, signature(action, error), tuple(between))
            if key in seen:
                continue
            seen.add(key)
            out.append({"kind": "precondition_failed", "action": name, "target": target,
                        "error": error, "carried_out_before_success": between})
        return out


def lesson_text(entry):
    target = f" on {entry['target']}" if entry.get("target") else ""
    between = ", ".join(entry.get("carried_out_before_success") or []) or "nothing else"
    return (f"{entry['action']}{target} was refused ({entry['error']}); it was carried out "
            f"after {between}.")


class ReflectionLibrary:
    """The JSONL library. Reads train entries only; writes only from a train run."""

    def __init__(self, path, *, brief=None, split=None):
        self.path = Path(path) if path else None
        self.brief = brief
        self.split = split or split_for(brief)

    @property
    def writable(self):
        return self.split == "train" and self.path is not None

    def read(self, limit=8):
        if self.path is None or not self.path.is_file():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return [row for row in rows if row.get("split") == "train"][-limit:]

    def write(self, lessons, *, run=None):
        """Append new lessons; return the rows written. Writes nothing unless this is a
        train run."""
        if not self.writable or not lessons:
            return []
        existing = {row.get("id") for row in self.read(limit=10**6)}
        written = []
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        for lesson in lessons:
            body = {k: lesson[k] for k in sorted(lesson)}
            digest = hashlib.sha256(json.dumps([self.brief, body], sort_keys=True)
                                    .encode("utf-8")).hexdigest()[:16]
            if digest in existing:
                continue
            written.append({"id": digest, "split": "train", "brief": self.brief, "run": run,
                            "written_at": stamp, **body, "text": lesson_text(body)})
        if written:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                for row in written:
                    stream.write(json.dumps(row, ensure_ascii=False)+"\n")
        return written

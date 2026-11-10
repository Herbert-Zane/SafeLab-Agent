"""What one robustness run shows, read from its own artifacts.

Inputs are the files a run directory already holds: ``agent_run.json`` and
``agent_steps.jsonl`` (written by the platform) and ``safelab_trace.jsonl``
(written by SafeLab). Nothing here calls a model.

Definitions used in the report:

* A **fault** is one ``fault`` event of the injector (``safelab.resilience``).
  It is **recovered** when the platform call it happened in, or the next one,
  ends with a well-formed action being returned. A retried timeout or 429 is
  recovered inside the same call; a garbled actor reply costs the turn (the
  platform reports an invalid reply) and is recovered on the next call.
* How a run **ended**:
  ``completed``      the agent's own ``finish``;
  ``safe_stop``      SafeLab ended the run itself with ``finish`` and a reason
                     (the reviewer's refusal limit, or its budget);
  ``backend_error``  retries ran out and the platform stopped the episode; no
                     action was executed after the failure;
  ``limit``          a platform ceiling (steps, invalid replies, failed
                     actions, tokens, cost, wall clock);
  ``other``          anything else, including a run that left no result file.
* **Blocked proposals** are the reviewer's ``block`` and ``rewrite`` verdicts
  (condition C only).
* **Flagged executed actions** come from replaying the run's observations
  through the rule channel offline: an action the platform carried out that
  rules R1-R6 would have refused on the ledger of that moment. This is the same
  rule set the reviewer uses, so in condition C it mostly reads zero; its use is
  to show what got through in condition B.

None of this is an evaluation result. A dry run has no consequence
recognition, and the rule replay is SafeLab's own rules, not the platform's
evaluator. Report these numbers as development signals only.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

SAFE_STOP_SOURCES = ("safelab_critic_stop", "safelab_budget_stop")
LIMIT_OUTCOMES = ("step_limit", "invalid_reply_limit", "action_failure_limit", "action_failed",
                  "budget_limit")
#: Per-step latency the demonstration mode aims for (execution plan S3.4).
VISIBLE_LATENCY_TARGET_S = 15.


def read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def well_formed(action):
    return isinstance(action, dict) and isinstance(action.get("action"), str)


def action_label(action):
    if not well_formed(action):
        return "unreadable"
    parts = [action["action"]]
    parts += [f"{key}={action[key]}" for key in sorted(action)
              if key not in ("action", "reason") and isinstance(action[key], str)]
    return " ".join(parts)


# -- faults ----------------------------------------------------------------------------------------


def fault_rows(trace):
    """One row per injected fault, with whether the run got past it."""
    returned = [row for row in trace if row.get("event") == "returned"]
    out = []
    for row in trace:
        if row.get("event") != "fault":
            continue
        call = row.get("call")
        recovered = any(r.get("seq", 0) > row.get("seq", 0) and call is not None
                        and r.get("call") in (call, call+1) and well_formed(r.get("action"))
                        for r in returned)
        out.append({"call": call, "role": row.get("role"), "kind": row.get("kind"),
                    "attempt": row.get("attempt"), "recovered": recovered})
    return out


def fault_summary(faults):
    by_kind = {}
    for row in faults:
        cell = by_kind.setdefault(row["kind"], {"injected": 0, "recovered": 0})
        cell["injected"] += 1
        cell["recovered"] += bool(row["recovered"])
    injected = len(faults)
    recovered = sum(1 for row in faults if row["recovered"])
    return {"injected": injected, "recovered": recovered,
            "recovery_rate": round(recovered/injected, 4) if injected else None,
            "by_kind": by_kind,
            "retries": None}


# -- how the run ended -----------------------------------------------------------------------------


def ending(agent_run, trace):
    if not agent_run:
        return "other"
    outcome = agent_run.get("outcome")
    last = next((row for row in reversed(trace) if row.get("event") == "returned"), None)
    if outcome == "finished_by_agent":
        if last is not None and last.get("source") in SAFE_STOP_SOURCES:
            return "safe_stop"
        return "completed"
    if outcome == "backend_error":
        return "backend_error"
    if outcome in LIMIT_OUTCOMES:
        return "limit"
    return "other"


def finish_reason(steps):
    """The reason text of the run's last ``finish``, if it ended on one."""
    for step in reversed(steps):
        action = step.get("parsed_action")
        if well_formed(action):
            return action.get("reason") if action["action"] == "finish" else None
    return None


# -- the reviewer ----------------------------------------------------------------------------------


def review_summary(trace):
    reviewed = [row for row in trace if row.get("event") == "reviewed"]
    counts = {}
    for row in reviewed:
        counts[row.get("decision")] = counts.get(row.get("decision"), 0)+1
    blocked = [{"call": row.get("call"), "decision": row.get("decision"),
                "action": action_label(row.get("proposed")), "rule_ids": row.get("rule_ids") or [],
                "channel": row.get("channel"), "reason": (row.get("reason") or "")[:240]}
               for row in reviewed if row.get("decision") in ("block", "rewrite")]
    return {"reviewed": len(reviewed), "decisions": counts, "blocked": blocked,
            "refusal_limit": [row.get("key") for row in trace
                              if row.get("event") == "refusal_limit"],
            "safe_stops": [row.get("source") for row in trace if row.get("event") == "returned"
                           and row.get("source") in SAFE_STOP_SOURCES]}


def flagged_executed(steps, make_ledger, check):
    """Executed actions the rule channel refuses on the ledger of that moment.

    ``make_ledger()`` returns a fresh ledger with ``update``, ``snapshot`` and ``expect``;
    ``check(snapshot, observation, action)`` returns the hard rule ids. Both are passed in so
    this module imports neither the platform nor the reviewer.
    """
    ledger = make_ledger()
    flagged = []
    for step in steps:
        observation = step.get("observation")
        if not isinstance(observation, dict):
            continue
        ledger.update(observation)
        action = step.get("parsed_action")
        if not well_formed(action) or action["action"] == "finish":
            continue
        rules = check(ledger.snapshot(), observation, action)
        if rules and step.get("status") == "complete":
            flagged.append({"step": step.get("step_index"), "action": action_label(action),
                            "rule_ids": sorted(rules)})
        ledger.expect(action)
    return flagged


def rule_replay():
    """The ledger factory and rule check for ``flagged_executed`` (needs ``src`` on the path)."""
    from safelab.critic.rules import RuleChannel
    from safelab.ledger import Ledger
    channel = RuleChannel()

    def check(snapshot, observation, action):
        return {finding.rule for finding in channel.check(snapshot, observation, action).hard}

    return Ledger, check


# -- time and cost ---------------------------------------------------------------------------------


def visible_latency(steps, target_s=VISIBLE_LATENCY_TARGET_S):
    """Seconds from the request for a step to its reply, per platform call.

    In a dry run the environment answers at once, so this is what an onlooker waits for
    between two actions. In the simulator the motion time comes on top of it.
    """
    values = [float((step.get("reply") or {})["latency_s"]) for step in steps
              if isinstance((step.get("reply") or {}).get("latency_s"), (int, float))]
    if not values:
        return {"steps": 0, "median_s": None, "max_s": None, "mean_s": None,
                "over_target": None, "target_s": target_s}
    return {"steps": len(values), "median_s": round(statistics.median(values), 2),
            "max_s": round(max(values), 2), "mean_s": round(statistics.fmean(values), 2),
            "over_target": sum(1 for value in values if value > target_s), "target_s": target_s}


def role_latency(trace):
    """Total and largest single-call latency per role, from the ``usage`` events."""
    out = {}
    for row in trace:
        if row.get("event") != "usage" or row.get("latency_s") is None:
            continue
        cell = out.setdefault(row.get("role"), {"calls": 0, "total_s": 0., "max_s": 0.})
        cell["calls"] += 1
        cell["total_s"] = round(cell["total_s"]+row["latency_s"], 3)
        cell["max_s"] = max(cell["max_s"], row["latency_s"])
    return out


def cost(agent_run, trace):
    end = next((row for row in reversed(trace) if row.get("event") == "run_end"), {})
    usage = end.get("usage") or {}
    return {"list_usd": usage.get("total_cost_usd"),
            "cache_adjusted_usd": usage.get("total_actual_cost_usd"),
            "platform_usd": ((agent_run or {}).get("usage") or {}).get("cost_usd")}


# -- one run ---------------------------------------------------------------------------------------


def summarise(run_dir, *, replay=None):
    """Everything above for one run directory. ``replay`` is ``rule_replay()`` or None."""
    run_dir = Path(run_dir)
    agent_run = read_json(run_dir/"agent_run.json")
    steps = read_jsonl(run_dir/"agent_steps.jsonl")
    trace = read_jsonl(run_dir/"safelab_trace.jsonl")
    faults = fault_rows(trace)
    summary = fault_summary(faults)
    summary["retries"] = sum(1 for row in trace if row.get("event") == "retry")
    flagged = None
    if replay is not None and steps:
        flagged = flagged_executed(steps, *replay)
    run = agent_run or {}
    return {"run": run_dir.name, "present": agent_run is not None,
            "condition": (run.get("backend") or {}).get("condition"),
            "task_id": run.get("task_id"), "brief": (run.get("brief") or {}).get("source"),
            "outcome": run.get("outcome"), "outcome_detail": run.get("outcome_detail"),
            "ending": ending(agent_run, trace), "finish_reason": finish_reason(steps),
            "model_calls": run.get("model_calls"),
            "actions_completed": run.get("actions_completed"),
            "actions_failed": run.get("actions_failed"),
            "invalid_replies": run.get("invalid_replies"),
            "faults": summary, "fault_rows": faults, "review": review_summary(trace),
            "flagged_executed": flagged,
            "visible_latency": visible_latency(steps), "role_latency": role_latency(trace),
            "cost": cost(agent_run, trace),
            "assessment": ((run.get("environment") or {}).get("assessment"))}


def aggregate(rows):
    """Recovery rate over all injected faults, and how the runs that did not complete ended."""
    injected = sum(row["faults"]["injected"] for row in rows)
    recovered = sum(row["faults"]["recovered"] for row in rows)
    endings = {}
    for row in rows:
        endings[row["ending"]] = endings.get(row["ending"], 0)+1
    stopped = [row for row in rows if row["ending"] != "completed"]
    controlled = [row for row in stopped if row["ending"] in ("safe_stop", "backend_error")]
    return {"runs": len(rows), "faults_injected": injected, "faults_recovered": recovered,
            "recovery_rate": round(recovered/injected, 4) if injected else None,
            "endings": endings, "not_completed": len(stopped),
            "controlled_stops": len(controlled),
            "controlled_stop_rate": round(len(controlled)/len(stopped), 4) if stopped else None,
            "blocked_proposals": sum(len(row["review"]["blocked"]) for row in rows),
            "flagged_executed": sum(len(row["flagged_executed"] or []) for row in rows)}

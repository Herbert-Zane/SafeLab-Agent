"""Fault tolerance around every sub-backend call.

Each role (planner, actor, later critic) talks to its model through a
``GuardedRole``, which adds, in this order:

1. a budget check: SafeLab's own per-model cost total plus a reserve for the
   next call must stay under ``budget_usd``, else ``BudgetExhausted`` is raised
   before any request is made (the backend then stops the episode with
   ``finish`` and says why);
2. fault injection, off unless the config turns it on: a timeout, a 429 or a
   garbled reply, by probability or at a given attempt of a given role;
3. a wall-clock timeout per call;
4. retry with exponential backoff and jitter on retryable errors. When the
   retries are used up, ``RetriesExhausted`` is raised and the backend hands
   the platform a ``BackendError``, which it records as ``backend_error``.

Every call's tokens and cost go into a ``UsageMeter`` by role and by model;
cost uses the same per-model price table the platform applies, so the total
is directly comparable with the platform's own figure.

This module does not import the platform. What counts as retryable, how a
price is resolved and how a reply object is built are passed in.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
_PRICE_KEYS = {"input_tokens": "input", "output_tokens": "output",
               "cache_read_tokens": "cache_read", "cache_write_tokens": "cache_write"}
FAULT_KINDS = ("timeout", "rate_limit", "garbled")
#: A reply with no JSON object in it, for the ``garbled`` fault.
GARBLED_TEXT = "��]] ::: \u0000reply lost in transit ::: [[�"


class CallTimeout(TimeoutError):
    """A sub-backend call did not return within the configured time."""


class InjectedFault(RuntimeError):
    """A failure produced by the fault injector, never by a provider."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class BudgetExhausted(RuntimeError):
    """The next call would take SafeLab's own spend past its budget."""


class RetriesExhausted(RuntimeError):
    def __init__(self, role, attempts, last):
        super().__init__(f"{role}: {attempts} attempts failed; last error: "
                         f"{type(last).__name__}: {last}")
        self.role, self.attempts, self.last = role, attempts, last


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 2
    backoff_s: float = 2.0
    backoff_max_s: float = 30.0
    jitter: float = 0.25
    call_timeout_s: float | None = 900.

    @classmethod
    def from_spec(cls, spec):
        spec = spec or {}
        known = {name: spec[name] for name in cls.__dataclass_fields__ if name in spec}
        policy = cls(**known)
        if policy.retries < 0 or policy.backoff_s < 0 or policy.backoff_max_s < 0:
            raise ValueError("retries and backoff must not be negative")
        return policy

    def delay(self, retry, rng):
        """Seconds to wait before retry number ``retry`` (0-based)."""
        base = min(self.backoff_max_s, self.backoff_s*(2**retry))
        return base*(1+self.jitter*rng.random()) if self.jitter and rng else base


def call_with_timeout(fn, timeout_s):
    """Run ``fn()``; raise ``CallTimeout`` if it has not returned after ``timeout_s``.

    The call runs on a daemon thread. A call that times out is abandoned, not
    killed; the provider SDK's own request timeout bounds how long it lingers.
    """
    if not timeout_s:
        return fn()
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # handed to the caller below
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True, name="safelab-call")
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise CallTimeout(f"no reply within {timeout_s:g} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


class UsageMeter:
    """Tokens and cost by role and by model.

    ``price_for(model) -> dict | None`` returns US dollars per million tokens
    with keys input, output, cache_read, cache_write. A model without a price
    is counted in tokens and reported as unpriced, never guessed.
    """

    def __init__(self, price_for=None):
        self.price_for = price_for or (lambda model: None)
        self.records = []

    def add(self, role, model, usage, *, latency_s=None, detail=None):
        """Record one call. ``cost_usd`` prices every input token at the input price,
        as the platform does; ``actual_cost_usd`` also prices the provider-reported
        prompt-cache hits in ``detail`` (``prompt_cache_hit_tokens``) at the cache-read
        price. Without a reported hit count the two are equal."""
        counts = {name: int(usage[name]) for name in USAGE_FIELDS
                  if usage and isinstance(usage.get(name), int)
                  and not isinstance(usage.get(name), bool)}
        prices = self.price_for(model)
        hits = (detail or {}).get("prompt_cache_hit_tokens")
        hits = hits if isinstance(hits, int) and not isinstance(hits, bool) and hits >= 0 \
            else None
        cost = actual = None
        if prices is not None:
            cost = round(sum(counts.get(name, 0)*prices[key]/1e6
                             for name, key in _PRICE_KEYS.items()), 8)
            actual = cost
            if hits:
                hits_priced = min(hits, counts.get("input_tokens", 0))
                actual = round(cost-hits_priced*(prices["input"]-prices["cache_read"])/1e6, 8)
        record = {"role": role, "model": model, "usage": counts, "cost_usd": cost,
                  "cache_hit_tokens": hits, "actual_cost_usd": actual, "latency_s": latency_s}
        self.records.append(record)
        return record

    @property
    def actual_spent_usd(self):
        """Spend with prompt-cache hits at the cache-read price (see ``add``)."""
        return round(sum(r["actual_cost_usd"] for r in self.records
                         if r.get("actual_cost_usd") is not None), 8)

    @property
    def spent_usd(self):
        return round(sum(r["cost_usd"] for r in self.records if r["cost_usd"] is not None), 8)

    def max_call_cost(self, role=None):
        costs = [r["cost_usd"] for r in self.records
                 if r["cost_usd"] is not None and (role is None or r["role"] == role)]
        return max(costs, default=0.)

    def usage_since(self, index):
        """Summed token counts of the records from ``index`` on, or None if none had any."""
        totals = dict.fromkeys(USAGE_FIELDS, 0)
        counted = False
        for record in self.records[index:]:
            for name, value in record["usage"].items():
                totals[name] += value
                counted = True
        return {k: v for k, v in totals.items() if v} if counted else None

    def latency_since(self, index):
        values = [r["latency_s"] for r in self.records[index:] if r["latency_s"] is not None]
        return sum(values) if values else None

    def report(self):
        def group(key):
            out = {}
            for record in self.records:
                row = out.setdefault(record[key], {"calls": 0, **dict.fromkeys(USAGE_FIELDS, 0),
                                                   "cache_hit_tokens": 0, "cost_usd": 0.,
                                                   "actual_cost_usd": 0., "latency_s": 0.,
                                                   "unpriced_calls": 0})
                row["calls"] += 1
                for name, value in record["usage"].items():
                    row[name] += value
                row["cache_hit_tokens"] += record.get("cache_hit_tokens") or 0
                row["latency_s"] = round(row["latency_s"]+(record.get("latency_s") or 0.), 3)
                if record["cost_usd"] is None:
                    row["unpriced_calls"] += 1
                else:
                    row["cost_usd"] = round(row["cost_usd"]+record["cost_usd"], 8)
                    row["actual_cost_usd"] = round(
                        row["actual_cost_usd"]+record.get("actual_cost_usd", record["cost_usd"]),
                        8)
            return out
        return {"by_model": group("model"), "by_role": group("role"),
                "total_cost_usd": self.spent_usd,
                "total_actual_cost_usd": self.actual_spent_usd, "calls": len(self.records)}


class Budget:
    """Stop before a call that could take the spend past ``limit_usd``.

    The reserve for the next call is the most expensive call this role has
    made so far -- or, before its first call, the most expensive call of any
    role -- and at least ``min_reserve_usd``.
    """

    def __init__(self, limit_usd, meter, *, min_reserve_usd=0.):
        self.limit_usd = None if limit_usd is None else float(limit_usd)
        self.meter = meter
        self.min_reserve_usd = float(min_reserve_usd)

    def check(self, role):
        if self.limit_usd is None:
            return
        reserve = max(self.meter.max_call_cost(role) or self.meter.max_call_cost(),
                      self.min_reserve_usd)
        spent = self.meter.spent_usd
        if spent+reserve > self.limit_usd:
            raise BudgetExhausted(
                f"spent ${spent:.4f}; the next {role} call (reserve ${reserve:.4f}) could pass "
                f"the SafeLab budget of ${self.limit_usd:.2f}")


class FaultInjector:
    """Config-driven faults; inert unless ``enabled`` is true.

    ``{"enabled": true, "seed": 0, "roles": ["actor"],
       "probability": {"timeout": 0.05, "rate_limit": 0.05, "garbled": 0.05},
       "at": [{"role": "actor", "attempt": 3, "kind": "rate_limit"}]}``

    ``attempt`` counts every request a role makes, retries included, from 1.
    """

    def __init__(self, spec=None):
        spec = spec or {}
        self.enabled = bool(spec.get("enabled", False))
        self.roles = set(spec["roles"]) if spec.get("roles") else None
        self.probability = {kind: float(p) for kind, p in (spec.get("probability") or {}).items()}
        self.at = [dict(row) for row in spec.get("at") or []]
        unknown = sorted(({*self.probability} | {row.get("kind") for row in self.at})
                         - set(FAULT_KINDS))
        if unknown:
            raise ValueError(f"Unknown fault kinds: {unknown}")
        self.rng = random.Random(spec.get("seed", 0))

    def draw(self, role, attempt):
        if not self.enabled or (self.roles is not None and role not in self.roles):
            return None
        for row in self.at:
            if row.get("role", role) == role and int(row.get("attempt", -1)) == attempt:
                return row["kind"]
        for kind in FAULT_KINDS:
            if self.rng.random() < self.probability.get(kind, 0.):
                return kind
        return None


class GuardedRole:
    """One role's sub-backend behind budget, faults, timeout and retry."""

    def __init__(self, name, backend, *, policy=None, meter=None, budget=None, faults=None,
                 is_retryable=lambda exc: True, make_reply=None, emit=None,
                 sleep=time.sleep, rng=None):
        self.name = name
        self.backend = backend
        self.policy = policy or RetryPolicy()
        self.meter = meter or UsageMeter()
        self.budget = budget
        self.faults = faults or FaultInjector()
        self.is_retryable = is_retryable
        self.make_reply = make_reply
        self.emit = emit or (lambda event, **fields: None)
        self.sleep = sleep
        self.rng = rng or random.Random(0)
        self.attempts = 0

    @property
    def model(self):
        return getattr(self.backend, "model", None)

    def _once(self, system, messages):
        kind = self.faults.draw(self.name, self.attempts)
        if kind is not None:
            self.emit("fault", role=self.name, attempt=self.attempts, kind=kind)
        if kind == "timeout":
            raise CallTimeout("injected timeout")
        if kind == "rate_limit":
            raise InjectedFault(kind, "Error code: 429 - injected rate limit")
        if kind == "garbled":
            if self.make_reply is None:
                raise InjectedFault(kind, "garbled reply (no reply factory configured)")
            return self.make_reply(GARBLED_TEXT, self.model)
        return call_with_timeout(lambda: self.backend.generate(system=system, messages=messages),
                                 self.policy.call_timeout_s)

    def generate(self, *, system, messages):
        retry = 0
        while True:
            if self.budget is not None:
                self.budget.check(self.name)
            self.attempts += 1
            started = time.monotonic()
            try:
                reply = self._once(system, messages)
            except Exception as exc:
                retryable = isinstance(exc, (CallTimeout, InjectedFault)) or self.is_retryable(exc)
                self.emit("call_error", role=self.name, attempt=self.attempts,
                          error=f"{type(exc).__name__}: {exc}", retryable=retryable)
                if not retryable:
                    raise
                if retry >= self.policy.retries:
                    raise RetriesExhausted(self.name, retry+1, exc) from exc
                delay = self.policy.delay(retry, self.rng)
                self.emit("retry", role=self.name, attempt=self.attempts, retry=retry+1,
                          delay_s=round(delay, 3))
                self.sleep(delay)
                retry += 1
                continue
            latency = getattr(reply, "latency_s", None)
            if latency is None:
                latency = time.monotonic()-started
            model = getattr(reply, "model", None) or self.model
            extra = getattr(reply, "extra", None) or {}
            record = self.meter.add(self.name, model, getattr(reply, "usage", None),
                                    latency_s=round(latency, 3),
                                    detail=extra.get("usage_detail"))
            self.emit("usage", role=self.name, attempt=self.attempts, model=model,
                      usage=record["usage"], cost_usd=record["cost_usd"],
                      actual_cost_usd=record["actual_cost_usd"],
                      latency_s=record["latency_s"],
                      stop_reason=getattr(reply, "stop_reason", None),
                      usage_detail=extra.get("usage_detail"),
                      spent_usd=self.meter.spent_usd)
            return reply

    def record(self):
        return self.backend.record()

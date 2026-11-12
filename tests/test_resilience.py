"""Retry, timeout, metering, budget and fault injection (no platform needed)."""
import time

import pytest

from fakes import FakeModel, FakeReply
from safelab.resilience import (
    GARBLED_TEXT,
    Budget,
    BudgetExhausted,
    CallTimeout,
    FaultInjector,
    GuardedRole,
    RetriesExhausted,
    RetryPolicy,
    UsageMeter,
    call_with_timeout,
)

PRICES = {"m-cheap": {"input": 1., "output": 2., "cache_read": .1, "cache_write": 1.25}}


class Flaky(RuntimeError):
    pass


def guarded(model, *, retries=2, budget=None, faults=None, timeout=None, retryable=True):
    events, sleeps = [], []
    meter = UsageMeter(price_for=PRICES.get)
    role = GuardedRole(
        "actor", model, policy=RetryPolicy(retries=retries, backoff_s=1., backoff_max_s=3.,
                                           jitter=0., call_timeout_s=timeout),
        meter=meter, budget=Budget(budget, meter) if budget is not None else None,
        faults=FaultInjector(faults), is_retryable=lambda exc: retryable,
        make_reply=lambda text, model: FakeReply(text=text, model=model),
        emit=lambda event, **fields: events.append((event, fields)), sleep=sleeps.append)
    return role, meter, events, sleeps


def test_a_transient_error_is_retried_with_growing_backoff():
    model = FakeModel(Flaky("503"), Flaky("503"), "ok")
    role, _, events, sleeps = guarded(model)
    assert role.generate(system="s", messages=[]).text == "ok"
    assert sleeps == [1., 2.]
    assert [e for e, _ in events] == ["call_error", "retry", "call_error", "retry", "usage"]


def test_backoff_is_capped():
    assert RetryPolicy(backoff_s=2., backoff_max_s=5., jitter=0.).delay(4, None) == 5.


def test_when_retries_run_out_the_last_error_is_reported():
    role, *_ = guarded(FakeModel(Flaky("a"), Flaky("b"), Flaky("c")), retries=2)
    with pytest.raises(RetriesExhausted, match="3 attempts failed.*Flaky: c"):
        role.generate(system="s", messages=[])


def test_a_non_retryable_error_is_raised_at_once():
    role, _, _, sleeps = guarded(FakeModel(Flaky("refused"), "ok"), retryable=False)
    with pytest.raises(Flaky):
        role.generate(system="s", messages=[])
    assert sleeps == []


class Slow:
    model = "m-cheap"

    def __init__(self, delays):
        self.delays = list(delays)

    def generate(self, *, system, messages):
        time.sleep(self.delays.pop(0))
        return FakeReply(text="late")


def test_a_call_past_its_timeout_is_abandoned_and_retried():
    role, _, events, _ = guarded(Slow([0.5, 0.]), timeout=0.05)
    assert role.generate(system="s", messages=[]).text == "late"
    assert "CallTimeout" in events[0][1]["error"]


def test_call_with_timeout_passes_values_and_errors_through():
    assert call_with_timeout(lambda: 7, 1.) == 7
    with pytest.raises(KeyError):
        call_with_timeout(lambda: {}["x"], 1.)
    with pytest.raises(CallTimeout):
        call_with_timeout(lambda: time.sleep(0.3), 0.01)


def test_usage_is_metered_per_model_and_per_turn():
    meter = UsageMeter(price_for=PRICES.get)
    meter.add("planner", "m-cheap", {"input_tokens": 1_000_000, "output_tokens": 500_000})
    mark = len(meter.records)
    meter.add("actor", "m-cheap", {"input_tokens": 2000, "cache_read_tokens": 1000})
    meter.add("actor", "m-unpriced", {"input_tokens": 10})
    assert meter.spent_usd == pytest.approx(2.0+0.002+0.0001)
    assert meter.usage_since(mark) == {"input_tokens": 2010, "cache_read_tokens": 1000}
    report = meter.report()
    assert report["by_model"]["m-unpriced"]["unpriced_calls"] == 1
    assert report["by_role"]["planner"]["cost_usd"] == pytest.approx(2.0)
    assert meter.usage_since(len(meter.records)) is None


@pytest.mark.parametrize("detail", [None, {"prompt_cache_hit_tokens": 64},
                                   {"prompt_cache_hit_tokens": 120}])
def test_separate_cache_counts_are_priced_once_even_with_raw_provider_detail(detail):
    meter = UsageMeter(price_for=PRICES.get)
    usage = {"input_tokens": 56, "output_tokens": 45, "cache_read_tokens": 64}
    record = meter.add("actor", "m-cheap", usage, detail=detail)
    assert record["cost_usd"] == pytest.approx(0.0001524)
    assert record["actual_cost_usd"] == record["cost_usd"]
    assert record["cache_hit_tokens"] == 64
    assert record["usage"] == usage
    assert meter.spent_usd == meter.actual_spent_usd == pytest.approx(0.0001524)
    report = meter.report()
    assert report["by_role"]["actor"]["cache_read_tokens"] == 64


def test_cache_read_and_write_counts_are_disjoint_from_input_and_budgeted():
    meter = UsageMeter(price_for=PRICES.get)
    record = meter.add("actor", "m-cheap", {"input_tokens": 10, "cache_read_tokens": 100,
                                          "cache_write_tokens": 20, "output_tokens": 5})
    assert record["cost_usd"] == pytest.approx((10+10+25+10)/1e6)
    assert record["actual_cost_usd"] == record["cost_usd"]
    budget = Budget(0.0001, meter)
    with pytest.raises(BudgetExhausted):
        budget.check("actor")


def test_the_budget_stops_before_a_call_that_could_pass_it():
    usage = {"input_tokens": 100_000}                      # $0.10 a call
    model = FakeModel(*(FakeReply(text="x", model="m-cheap", usage=usage) for _ in range(5)))
    role, meter, *_ = guarded(model, budget=0.25)
    role.generate(system="s", messages=[])
    role.generate(system="s", messages=[])
    with pytest.raises(BudgetExhausted, match="SafeLab budget"):
        role.generate(system="s", messages=[])
    assert len(model.calls) == 2 and meter.spent_usd == pytest.approx(0.2)


def test_faults_are_off_unless_enabled():
    injector = FaultInjector({"probability": {"rate_limit": 1.}})
    assert injector.draw("actor", 1) is None
    with pytest.raises(ValueError, match="Unknown fault kinds"):
        FaultInjector({"enabled": True, "probability": {"meteor": 1.}})


def test_an_injected_429_at_a_given_attempt_is_retried():
    faults = {"enabled": True, "at": [{"role": "actor", "attempt": 1, "kind": "rate_limit"}]}
    role, _, events, sleeps = guarded(FakeModel("ok"), faults=faults)
    assert role.generate(system="s", messages=[]).text == "ok"
    assert [e for e, _ in events][:3] == ["fault", "call_error", "retry"]
    assert "429" in events[1][1]["error"] and sleeps == [1.]


def test_injected_timeouts_and_garbled_replies():
    faults = {"enabled": True, "at": [{"attempt": 1, "kind": "timeout"},
                                      {"attempt": 2, "kind": "garbled"}]}
    model = FakeModel("never used")
    role, *_ = guarded(model, faults=faults)
    assert role.generate(system="s", messages=[]).text == GARBLED_TEXT
    assert model.calls == []
    assert "{" not in GARBLED_TEXT


def test_probabilistic_faults_are_reproducible_by_seed():
    spec = {"enabled": True, "seed": 3, "probability": {"garbled": 0.5}, "roles": ["actor"]}
    first, second = FaultInjector(spec), FaultInjector(spec)
    draws = [first.draw("actor", n) for n in range(1, 21)]
    assert draws == [second.draw("actor", n) for n in range(1, 21)]
    assert {"garbled", None} == set(draws)
    assert FaultInjector(spec).draw("planner", 1) is None


def test_negative_retry_settings_are_refused():
    with pytest.raises(ValueError):
        RetryPolicy.from_spec({"retries": -1})
    assert RetryPolicy.from_spec({"retries": 0, "ignored": 1}).retries == 0

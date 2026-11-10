"""The reasoning-keeping role backend and the Flash config (needs the platform; no network).

The request condition B sends must be byte-for-byte the request condition A
sends. These tests build both backends from the same spec, with fake clients,
and compare what reaches the client.
"""
import json
from types import SimpleNamespace

import pytest

from safelab import launch

A_CONFIG = launch.CONFIG_DIR/"deepseek_flash.json"
B_CONFIG = launch.CONFIG_DIR/"safelab_B_flash.json"
ACTION = '```json\n{"action": "finish"}\n```'


def response(content=ACTION, reasoning="Because the tube is open.", usage=True):
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    counts = SimpleNamespace(
        prompt_tokens=120, completion_tokens=45, prompt_cache_hit_tokens=64,
        prompt_cache_miss_tokens=56,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=40)) if usage else None
    return SimpleNamespace(id="req-1", model="deepseek-flash", usage=counts,
                           choices=[SimpleNamespace(message=message, finish_reason="stop")])


class FakeClient:
    def __init__(self, reply):
        self.reply, self.requests = reply, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **body):
        self.requests.append(body)
        return self.reply


def backend_spec(path, role=None):
    backend = json.loads(path.read_text(encoding="utf-8"))["backend"]
    return backend["roles"][role] if role else backend


def both(reply):
    from agent_interface.backends.openai_compatible import OpenAICompatibleBackend

    from safelab.openai_reasoning import ReasoningOpenAIBackend
    a_client, b_client = FakeClient(reply), FakeClient(reply)
    a = OpenAICompatibleBackend(backend_spec(A_CONFIG), api_key="k", client=a_client)
    b = ReasoningOpenAIBackend(backend_spec(B_CONFIG, "actor"), api_key="k", client=b_client)
    messages = [{"role": "user", "content": "Observed state: ..."}]
    return (a.generate(system="sys", messages=messages), a_client,
            b.generate(system="sys", messages=messages), b_client)


def test_the_request_is_identical_to_condition_a_s(bench):
    a_reply, a_client, b_reply, b_client = both(response())
    assert a_client.requests == b_client.requests
    body = b_client.requests[0]
    assert (body["model"], body["max_tokens"], body["reasoning_effort"]) == (
        "deepseek-flash", 16000, "high")
    assert body["extra_body"] == {"thinking": {"type": "enabled"}}
    assert (b_reply.text, b_reply.usage, b_reply.stop_reason) == (
        a_reply.text, a_reply.usage, a_reply.stop_reason)
    assert b_reply.usage == {"input_tokens": 120, "output_tokens": 45}


def test_reasoning_and_token_detail_are_kept(bench):
    a_reply, _, b_reply, _ = both(response())
    assert a_reply.thinking is None
    assert b_reply.thinking == "Because the tube is open."
    assert b_reply.extra["usage_detail"] == {
        "prompt_tokens": 120, "completion_tokens": 45, "prompt_cache_hit_tokens": 64,
        "prompt_cache_miss_tokens": 56, "reasoning_tokens": 40}


def test_an_empty_answer_still_carries_its_reasoning(bench):
    _, _, b_reply, _ = both(response(content="", reasoning="ran out of budget", usage=False))
    assert b_reply.text == "" and b_reply.thinking == "ran out of budget"
    assert "usage_detail" not in b_reply.extra


def test_the_sdk_client_is_built_with_the_same_options(bench, monkeypatch):
    import openai
    from agent_interface.backends.openai_compatible import OpenAICompatibleBackend

    from safelab.openai_reasoning import ReasoningOpenAIBackend
    built = []
    monkeypatch.setattr(openai, "OpenAI", lambda **options: built.append(options) or object())
    _ = OpenAICompatibleBackend(backend_spec(A_CONFIG), api_key="k").client
    _ = ReasoningOpenAIBackend(backend_spec(B_CONFIG, "planner"), api_key="k").client
    assert built[0] == built[1] == {"max_retries": 3, "timeout": 300, "api_key": "k",
                                    "base_url": "https://api.deepseek.com"}


# -- the Flash config -------------------------------------------------------------


def test_every_role_uses_condition_a_s_exact_request_settings():
    a = backend_spec(A_CONFIG)
    b = backend_spec(B_CONFIG)
    strip = {"provider"}
    for role in ("planner", "actor"):
        spec = b["roles"][role]
        assert spec["provider"] == "openai_compatible_reasoning"
        assert {k: v for k, v in spec.items() if k not in strip} == \
            {k: v for k, v in a.items() if k not in strip}, role


def test_the_platform_is_charged_at_the_dearest_role_price_and_limits_hold():
    config = json.loads(B_CONFIG.read_text(encoding="utf-8"))
    backend = config["backend"]
    prices = backend["pricing"]
    dearest = max({spec["model"] for spec in backend["roles"].values()},
                  key=lambda m: (prices[m]["input"], prices[m]["output"]))
    assert backend["model"] == dearest
    assert config["pricing_overrides"][dearest] == prices[dearest]
    a = json.loads(A_CONFIG.read_text(encoding="utf-8"))
    assert config["pricing_overrides"] == a["pricing_overrides"]
    assert config["limits"]["max_cost_usd"] <= 0.5
    assert backend["resilience"]["budget_usd"] < config["limits"]["max_cost_usd"]
    assert backend["resilience"]["faults"]["enabled"] is False
    assert config["policy"]["conversation"] == "stateless"


def test_the_flash_config_builds_without_a_network_call(bench, monkeypatch, tmp_path):
    from agent_interface.config import AgentRunConfig

    from safelab.backend import SafeLabBackend
    from safelab.openai_reasoning import ReasoningOpenAIBackend
    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder-for-test")
    config = AgentRunConfig.load(B_CONFIG)
    backend = SafeLabBackend(config.backend, run_dir=tmp_path)
    assert {name: type(role.backend) for name, role in backend.roles.items()} == {
        "planner": ReasoningOpenAIBackend, "actor": ReasoningOpenAIBackend}
    record = backend.record()
    assert record["roles"]["actor"]["keeps_reasoning_content"] is True
    assert record["components"]["planner"] == "model_stage_plan"
    assert record["is_model"] is True
    assert "placeholder-for-test" not in json.dumps(record)
    assert backend.budget.limit_usd == pytest.approx(0.45)

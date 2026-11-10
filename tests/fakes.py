"""Model stand-ins for tests: no network, no spend.

``FakeModel`` is for the platform-free modules. ``register_platform_fake``
adds provider ``"safelab_fake"`` to the platform registry (tests only): a
scripted backend that can also report token usage, carry reasoning text and
raise errors, which the platform's own ``scripted`` backend cannot.
"""
import json
from dataclasses import dataclass, field

FAKE_PROVIDER = "safelab_fake"


@dataclass
class FakeReply:
    text: str
    model: str | None = "fake-model"
    usage: dict | None = None
    thinking: str | None = None
    stop_reason: str | None = "stop"
    stop_details: dict | None = None
    latency_s: float | None = 0.
    provider_request_id: str | None = None
    extra: dict = field(default_factory=dict)


class FakeModel:
    """Replies in order: a string, a FakeReply, or an exception instance to raise."""

    def __init__(self, *replies, model="fake-model"):
        self.replies = list(replies)
        self.model = model
        self.calls = []

    def generate(self, *, system, messages):
        self.calls.append({"system": system, "messages": messages})
        if not self.replies:
            raise AssertionError("FakeModel has no reply left")
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item if isinstance(item, FakeReply) else FakeReply(text=item, model=self.model)

    def record(self):
        return {"provider": "fake", "model": self.model, "is_model": False}


def action_text(action, prose=""):
    return f"{prose}```json\n{json.dumps(action)}\n```"


def plan_text(*stages):
    return "```json\n" + json.dumps({"stages": list(stages)}) + "\n```"


def stage(name, expected, *, subgoal=None, preconditions=(), max_actions=None):
    out = {"name": name, "subgoal": subgoal or f"Do {name}.",
           "preconditions": list(preconditions), "expected": list(expected)}
    if max_actions is not None:
        out["max_actions"] = max_actions
    return out


def check(entity, field_, op, value):
    return {"entity": entity, "field": field_, "op": op, "value": value}


def register_platform_fake():
    from agent_interface.backends import (
        BackendError,
        BackendReply,
        backend_providers,
        register_backend,
    )

    class PlatformFake:
        provider = FAKE_PROVIDER

        def __init__(self, spec, **_):
            self.model = spec.get("model", "fake-model")
            self.replies = list(spec.get("replies") or [])
            self.calls = []

        def generate(self, *, system, messages):
            self.calls.append({"system": system, "messages": messages})
            if not self.replies:
                raise BackendError("The fake backend has no reply left")
            item = self.replies.pop(0)
            if isinstance(item, str):
                item = {"text": item}
            if item.get("error"):
                raise BackendError(item["error"])
            return BackendReply(text=item.get("text", ""), model=self.model,
                                stop_reason=item.get("stop_reason", "stop"),
                                usage=item.get("usage"), latency_s=0.,
                                thinking=item.get("thinking"))

        def record(self):
            return {"provider": self.provider, "model": self.model, "is_model": False}

    if FAKE_PROVIDER not in backend_providers():
        register_backend(FAKE_PROVIDER, lambda spec, **kw: PlatformFake(spec))

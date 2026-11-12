"""An OpenAI-compatible role backend that keeps the model's reasoning text.

The platform's ``openai_compatible`` backend already keeps reasoning text.
This subclass also keeps detailed provider usage metadata. It changes nothing
about the request: it inherits
``request_body``, the client settings (base URL, timeout, SDK retries) and the
whole of ``generate`` from the platform class, and only looks at more of the
response that call already received:

* ``thinking`` -- ``message.reasoning_content``, when the provider sends one;
* ``extra["usage_detail"]`` -- prompt cache hit/miss and reasoning token
  counts, when the provider reports them.

``usage`` keeps the platform's convention (input = uncached prompt tokens,
cache_read = cached prompt tokens, output = completion tokens), so condition B
is costed exactly the way condition A is.

The role spec uses ``"provider": "openai_compatible_reasoning"`` with the same
keys as a platform ``openai_compatible`` spec. SafeLab builds it itself; it is
not registered with the platform. Importable only after
``safelab.bench.ensure_importable()``.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from agent_interface.backends.openai_compatible import OpenAICompatibleBackend

PROVIDER = "openai_compatible_reasoning"
_DETAIL_FIELDS = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens",
                  "prompt_cache_miss_tokens")


class _RecordingClient:
    """Forwards ``chat.completions.create`` unchanged and keeps the raw response."""

    def __init__(self, client, sink):
        self._client, self._sink = client, sink
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **body):
        response = self._client.chat.completions.create(**body)
        self._sink.append(response)
        return response


def _field(obj, name):
    value = getattr(obj, name, None)
    if value is None and isinstance(getattr(obj, "model_extra", None), dict):
        value = obj.model_extra.get(name)
    return value


def usage_detail(response):
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    detail = {name: _field(usage, name) for name in _DETAIL_FIELDS}
    reasoning = _field(_field(usage, "completion_tokens_details") or SimpleNamespace(),
                       "reasoning_tokens")
    detail["reasoning_tokens"] = reasoning
    detail = {k: v for k, v in detail.items() if isinstance(v, int) and not isinstance(v, bool)}
    return detail or None


class ReasoningOpenAIBackend(OpenAICompatibleBackend):
    provider = PROVIDER

    def __init__(self, spec, *, api_key=None, client=None, **_):
        super().__init__(spec, api_key=api_key, client=client)
        self._sink = []

    @property
    def client(self):
        return _RecordingClient(OpenAICompatibleBackend.client.fget(self), self._sink)

    def generate(self, *, system, messages):
        self._sink = []
        reply = super().generate(system=system, messages=messages)
        response = self._sink[-1] if self._sink else None
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        reasoning = _field(message, "reasoning_content") if message is not None else None
        detail = usage_detail(response)
        extra = dict(reply.extra or {})
        if detail:
            extra["usage_detail"] = detail
        return replace(reply, thinking=reasoning if isinstance(reasoning, str) and reasoning
                       else reply.thinking, extra=extra)

    def record(self):
        return {**super().record(), "provider": self.provider,
                "request_built_by": "agent_interface openai_compatible (inherited, unchanged)",
                "keeps_reasoning_content": True}

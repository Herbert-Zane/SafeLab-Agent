"""Read the per-turn user message the platform sends to a backend.

The platform renders every turn with ``agent_interface.prompt.observation_text``:
optional feedback, then ``Observed state:`` and the observation as a ```json
block, then ``Give the next single action.`` In stateless mode the feedback
also carries a recap of the actions carried out so far.

This module only splits that text back into its parts. It does not need the
platform installed; ``tests/test_obs.py`` checks it against the platform's own
renderer whenever the platform is available, so a format change fails loudly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

OBSERVATION_MARKER = "Observed state:"
FAILED_PREFIX = "That action was not carried out:"
INVALID_PREFIX = "That reply could not be used:"
RECAP_PREFIXES = ("Actions carried out so far:", "No actions have been carried out yet.")


class ObservationParseError(ValueError):
    """The message did not contain an observation block in the platform's format."""


@dataclass(frozen=True)
class StepMessage:
    observation: dict
    #: The platform's own failure text for the previous turn, verbatim, if any.
    feedback: str | None = None
    #: ``"action_failed"``, ``"invalid_reply"``, ``"other"`` or ``None``.
    feedback_kind: str | None = None
    #: The stateless-mode recap of carried-out actions, if any.
    recap: str | None = None


def message_text(content):
    """A message's text, whether it is a string or a list of text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content
                         if isinstance(block, dict) and block.get("type") == "text")
    raise ObservationParseError("Message content must be a string or a list of text blocks")


def parse_step_message(content):
    text = message_text(content)
    marker = text.rfind(OBSERVATION_MARKER)
    if marker < 0:
        raise ObservationParseError(f"No {OBSERVATION_MARKER!r} section in the message")
    opening = text.find("```json", marker)
    if opening < 0:
        raise ObservationParseError("No ```json block after the observation marker")
    body_start = text.find("\n", opening)
    closing = text.find("\n```", body_start)
    if body_start < 0 or closing < 0:
        raise ObservationParseError("The observation block is not closed")
    try:
        observation = json.loads(text[body_start+1:closing])
    except json.JSONDecodeError as exc:
        raise ObservationParseError(f"The observation block is not valid JSON: {exc}") from exc
    if not isinstance(observation, dict):
        raise ObservationParseError("The observation block is not a JSON object")

    preamble = text[:marker].strip()
    recap = None
    starts = [preamble.find(prefix) for prefix in RECAP_PREFIXES if prefix in preamble]
    if starts:
        cut = min(starts)
        recap = preamble[cut:].strip() or None
        preamble = preamble[:cut].strip()
    feedback = preamble or None
    if feedback is None:
        kind = None
    elif feedback.startswith(FAILED_PREFIX):
        kind = "action_failed"
    elif feedback.startswith(INVALID_PREFIX):
        kind = "invalid_reply"
    else:
        kind = "other"
    return StepMessage(observation=observation, feedback=feedback, feedback_kind=kind,
                       recap=recap)

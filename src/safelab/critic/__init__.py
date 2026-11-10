"""SafeLab's safety critic (condition C): rule channel, LLM channel and the gate.

Public interface (stable; the offline critic benchmark calls exactly this)::

    from safelab.critic import Critic, Verdict

    critic = Critic.from_config(dict_or_path, mode="rules" | "llm" | "dual")
    verdict = critic.review(snapshot, observation, action)   # -> Verdict

``Critic.from_config(config, mode=None, *, backend=None, ...)``
    ``config`` is a dict or a path to a JSON file, in any of these shapes:

    * a SafeLab agent config, e.g. ``configs/agents/safelab_C_flash.json``:
      settings from ``backend.critic``, model from ``backend.roles.critic``,
      prices from ``backend.pricing``;
    * a plain platform agent config, e.g. ``configs/agents/deepseek_flash.json``
      or ``deepseek_v4_pro.json``: its ``backend`` is the critic's model, its
      ``pricing_overrides`` the prices;
    * a settings dict: ``{"mode", "llm_trigger", "max_llm_attempts",
      "model": {...model spec...}, "pricing": {...}}``.

    ``mode`` overrides the configured mode (default ``"dual"``). ``"rules"``
    needs no model and no network. ``"llm"`` and ``"dual"`` build the model
    from the config (this imports the BSLBench platform and reads the API key
    from the environment variable the spec names), unless ``backend=`` passes
    any object with ``generate(system=..., messages=...)`` (tests, fakes).

``Critic.review(snapshot, observation, action) -> Verdict``
    ``snapshot`` is ``safelab.ledger.Ledger.snapshot()`` taken after the
    ledger read the observation; ``observation`` is the platform observation
    that produced it (agent-visible; checked with the platform's
    ``assert_no_evaluator_state`` when the platform is importable);
    ``action`` is the proposed platform action dict. ``finish`` and non-dict
    actions pass without review.

``Verdict`` fields
    ``decision``        ``"pass"`` | ``"block"`` | ``"rewrite"``
    ``rule_ids``        every rule that fired (``"R1"``..``"R6"``), soft ones
                        included -- ``decision`` says what came of them
    ``card_ids``        knowledge cards the decision rests on
    ``evidence``        ``[{"path", "value"}]`` ledger paths (``action.<key>``
                        for the proposal) with the values found there
    ``rewrite``         the replacement action when ``decision == "rewrite"``
                        (an LLM rewrite only of an allowed kind; feasible now
                        and re-checked by the rule channel)
    ``confidence``      1.0 for a rule decision, the model's for an LLM one,
                        None when nothing reviewed it
    ``reason``          plain-language reason
    ``channel``         ``"rules"`` | ``"llm"`` | ``"rules+llm"`` | ``"none"``
    ``usage``           ``{"input_tokens", "output_tokens", ..., "llm_calls",
                        "cost_usd", "cache_hit_tokens", "actual_cost_usd",
                        "llm_latency_s", "latency_s"}`` for this review
                        (``actual_cost_usd`` prices provider-reported prompt
                        cache hits at the cache-read price)
    also: ``risk_category``, ``mode``, ``feedback`` (text for the actor),
    ``rules`` and ``llm`` (each channel's full record), ``llm_triggered``,
    ``trigger``, ``disagreement``, ``rewrite_rejected``; ``record()`` gives
    all of it as a JSON-serialisable dict.

``Critic.stats()``
    review count, LLM trigger ratio, LLM tokens, estimated tokens saved by the
    risk trigger, decision and disagreement counts.

Modes, merging and the risk trigger are described in ``gate``; rules R1-R6 in
``rules``; the evidence check in ``llm_critic``; cards, families and evidence
grades in ``knowledge``.

The critic reads only the ledger, the agent-visible observation, the proposed
action and its own knowledge files. It never reads the platform's evaluator
configuration, task criteria or consequence models.
"""
from .gate import Critic, Verdict

__all__ = ["Critic", "Verdict"]

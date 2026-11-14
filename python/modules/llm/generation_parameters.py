"""Provider-scoped generation capabilities shared with the renderer's JSON resolver.

Rules use the Python/JavaScript common regex subset and replace, rather than
merge, parameter maps. Unknown gateways retain numeric compatibility without
inheriting reasoning behavior from a coincidentally familiar model name.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from .providers import normalize_llm_provider

NUMERIC_GENERATION_FIELDS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "frequency_penalty",
    "presence_penalty",
    "repetition_penalty",
)
NEUTRAL_GENERATION_VALUES = {
    "top_k": 0.0,
    "min_p": 0.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
}


@lru_cache(maxsize=1)
def load_generation_parameter_registry() -> dict[str, Any]:
    # This file lives beside the module so packaged Python runtimes retain it.
    return json.loads(
        Path(__file__)
        .with_name("generation-parameters.registry.json")
        .read_text(encoding="utf-8")
    )


def clean_reasoning_effort(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized and normalized != "default" else None


def resolve_generation_capabilities(
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    registry = load_generation_parameter_registry()
    provider_name = normalize_llm_provider(provider)
    model_name = str(model or "").strip().lower().removeprefix("models/")
    capabilities = deepcopy(
        registry["providers"].get(provider_name, registry["providers"]["custom"])
    )
    for rule in registry["rules"]:
        if rule["provider"] == provider_name and re.search(
            rule["pattern"], model_name, re.IGNORECASE
        ):
            capabilities.update(
                deepcopy(
                    {
                        key: value
                        for key, value in rule.items()
                        if key not in {"provider", "pattern"}
                    }
                )
            )
    effort = clean_reasoning_effort(reasoning_effort)
    if capabilities.get("samplingRequiresNone") and (
        effort != "none" or effort not in capabilities["reasoningEfforts"]
    ):
        for field in ("temperature", "top_p"):
            capabilities["parameters"].pop(field, None)
    return capabilities


def generation_number(
    field: str, value: object, bounds: dict[str, Any] | None = None
) -> int | float | None:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float, str))
    ):
        return None
    try:
        numeric = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric == NEUTRAL_GENERATION_VALUES.get(field):
        return None
    if bounds is not None:
        numeric = max(bounds["min"], min(bounds["max"], numeric))
    if field == "top_k":
        numeric = int(numeric)
    return None if numeric == NEUTRAL_GENERATION_VALUES.get(field) else numeric


def filter_generation_parameters(
    body: dict[str, Any], provider: str | None
) -> dict[str, Any]:
    """Mutate the internal OpenAI-shaped body; native adapters map validated effort.

    Keep the canonical reasoning_effort until the last native conversion. Gemini's
    /openai endpoint accepts this same field, avoiding any unsupported extra keys.
    """
    provider_name = normalize_llm_provider(provider)
    effort = clean_reasoning_effort(body.get("reasoning_effort"))
    caps = resolve_generation_capabilities(provider_name, body.get("model"), effort)
    if effort not in caps["reasoningEfforts"]:
        effort = None
    # Remove stale provider-specific fields, including fields left by old settings.
    thinking = body.pop("thinking", None)
    body.pop("reasoning_effort", None)
    body.pop("enable_thinking", None)
    body.pop("thinking_config", None)
    if isinstance(body.get("output_config"), dict):
        output_config = dict(body["output_config"])
        output_config.pop("effort", None)
        if output_config:
            body["output_config"] = output_config
        else:
            body.pop("output_config", None)
    repeat_penalty = body.pop("repeat_penalty", None)
    if (
        provider_name == "lmstudio"
        and "repetition_penalty" not in body
        and repeat_penalty is not None
    ):
        body["repetition_penalty"] = repeat_penalty
    for field in NUMERIC_GENERATION_FIELDS:
        value = body.pop(field, None)
        bounds = caps["parameters"].get(field)
        if bounds is not None:
            numeric = generation_number(field, value, bounds)
            if numeric is not None:
                body[field] = numeric
    transport = caps["reasoningTransport"]
    thinking_type = thinking.get("type") if isinstance(thinking, dict) else None
    if transport == "deepseek_thinking":
        if effort == "none" or thinking_type == "disabled":
            body["thinking"] = {"type": "disabled"}
            effort = None
            # Flash non-thinking top_p is fixed at 1 and ignored upstream.
            body.pop("top_p", None)
        else:
            if effort or thinking_type == "enabled":
                body["thinking"] = {"type": "enabled"}
            if effort:
                body["reasoning_effort"] = effort
    elif transport == "enable_thinking":
        if effort:
            body["enable_thinking"] = effort != "none"
            if effort not in {"none", "auto"}:
                body["reasoning_effort"] = effort
            if (
                effort != "none"
                and str(body.get("model", "")).lower().startswith("qwen3.8")
                and "temperature" in body
            ):
                body["temperature"] = max(0.6, body["temperature"])
    elif effort and transport != "none":
        body["reasoning_effort"] = effort
    token_field = caps["outputTokenField"]
    token_value = body.get(token_field)
    for field in ("max_tokens", "max_completion_tokens"):
        value = body.pop(field, None)
        if token_value is None:
            token_value = value
    if token_value is not None:
        body[token_field] = token_value
    return caps


def map_compatible_generation_parameters(
    body: dict[str, Any], provider: str | None
) -> None:
    """Translate canonical numeric names after capability filtering."""
    if normalize_llm_provider(provider) == "lmstudio" and "repetition_penalty" in body:
        body["repeat_penalty"] = body.pop("repetition_penalty")

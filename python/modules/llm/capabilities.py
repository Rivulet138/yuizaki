"""Conservative model capability registry used for runtime safety gates."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal

VisionSupport = Literal["supported", "unsupported", "unknown"]
CapabilitySupport = Literal["supported", "unsupported", "unknown"]


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "electron" / "src" / "shared" / "model-capabilities.registry.json"


@lru_cache(maxsize=1)
def load_model_capability_registry() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key).lower(): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def get_model_capabilities(provider: str | None, model: str | None) -> dict[str, Any] | None:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower().removeprefix("models/")
    capability = load_model_capability_registry().get(f"{normalized_provider}:{normalized_model}")
    return dict(capability) if capability is not None else None


def get_model_limits(provider: str | None, model: str | None) -> dict[str, int]:
    """Return numeric limits only when the registry explicitly declares them.

    Unknown providers/models intentionally return an empty mapping so a custom
    endpoint keeps its existing behavior instead of inheriting guessed limits.
    """
    registered = get_model_capabilities(provider, model)
    if registered is None:
        return {}
    metadata = registered.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    limits: dict[str, int] = {}
    context_window = _positive_int(metadata.get("contextWindowTokens"))
    max_output = _positive_int(metadata.get("maxOutputTokens"))
    if context_window is not None:
        limits["context_window_tokens"] = context_window
    if max_output is not None:
        limits["max_output_tokens"] = max_output
    return limits


def infer_model_vision_support(provider: str | None, model: str | None) -> VisionSupport:
    """Return only capabilities known well enough to change request behavior."""
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_model.startswith("models/"):
        normalized_model = normalized_model.removeprefix("models/")
    registered = get_model_capabilities(normalized_provider, normalized_model)
    if registered is not None:
        vision = registered.get("vision")
        if vision is True:
            return "supported"
        if vision is False:
            return "unsupported"
    return "unknown"


def infer_model_capability_support(
    provider: str | None,
    model: str | None,
    capability: str,
) -> CapabilitySupport:
    """Return an explicit registry decision without guessing unknown providers."""
    registered = get_model_capabilities(provider, model)
    if registered is None:
        return "unknown"
    value = registered.get(capability)
    if value is True:
        return "supported"
    if value is False:
        return "unsupported"
    return "unknown"

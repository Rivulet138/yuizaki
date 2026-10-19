"""Conservative model capability registry used for runtime safety gates."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal

VisionSupport = Literal["supported", "unsupported", "unknown"]
CapabilitySupport = Literal["supported", "unsupported", "unknown"]

logger = logging.getLogger(__name__)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


_MODULE_DIR = Path(__file__).resolve().parent
# Canonical registry ships with the Python package so packaged runtimes keep it.
# The Electron shared path is kept as a legacy override for older checkouts.
_REGISTRY_CANDIDATES = (
    _MODULE_DIR / "model-capabilities.registry.json",
    _MODULE_DIR.parents[2] / "electron" / "src" / "shared" / "model-capabilities.registry.json",
)


def _registry_path() -> Path:
    override = os.getenv("YUIZAKI_MODEL_CAPABILITIES_REGISTRY", "").strip()
    if override:
        return Path(override)
    for candidate in _REGISTRY_CANDIDATES:
        if candidate.exists():
            return candidate
    return _REGISTRY_CANDIDATES[0]


@lru_cache(maxsize=1)
def load_model_capability_registry() -> dict[str, dict[str, Any]]:
    path = _registry_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Model capability registry unavailable at %s; model limits and vision "
            "support fall back to unknown: %s",
            path,
            exc,
        )
        return {}
    if not isinstance(payload, dict):
        logger.warning("Model capability registry at %s is not a JSON object", path)
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

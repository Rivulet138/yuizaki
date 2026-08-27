"""Unified, read-only runtime provider status for the local settings UI.

The registry deliberately projects only configuration metadata and health state.
Secrets and provider-specific client internals stay behind the existing probes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from ..llm.client import redact_error_text

ProviderHealth = Callable[[], Awaitable[tuple[bool, str]]]
ProviderClient = Callable[[], Any]

SCHEMA_VERSION = 1
HEALTH_PROBE_TIMEOUT_SECONDS = 3.0
logger = logging.getLogger(__name__)

_AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+")
_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_message(value: Any, fallback: str) -> str:
    text = str(value or fallback)
    text = _URL_USERINFO.sub(r"\1<redacted>@", text)
    text = _AUTHORIZATION.sub(r"\1<redacted>", text)
    return redact_error_text(text, limit=240)


def _diagnostic_error(code: str, exc: Exception) -> str:
    return _safe_message(f"{code}: {type(exc).__name__}: {exc}", code)


def _section(snapshot: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = snapshot.get(name)
    return value if isinstance(value, Mapping) else {}


async def _probe_health(probe: ProviderHealth | None, available: bool) -> tuple[bool, str]:
    if probe is None:
        return available, "Runtime available" if available else "Runtime unavailable"
    try:
        healthy, message = await asyncio.wait_for(probe(), timeout=HEALTH_PROBE_TIMEOUT_SECONDS)
        return bool(healthy), _safe_message(message, "Health probe completed")
    except asyncio.TimeoutError:
        return False, "Health probe timed out"
    except ConnectionError:
        return False, "Provider connection unavailable"
    except Exception as exc:  # noqa: BLE001 - injected probes may raise provider-specific exceptions.
        return False, _safe_message(f"Health probe failed: {exc}", "Health probe failed")


async def build_provider_registry_snapshot(
    *,
    config_snapshot_provider: Callable[[], Mapping[str, Any]],
    health_providers: Mapping[str, ProviderHealth],
    client_providers: Mapping[str, ProviderClient],
) -> dict[str, Any]:
    """Return a stable provider matrix suitable for settings and diagnostics."""

    config_diagnostic_error: str | None = None
    try:
        config = config_snapshot_provider()
    except Exception as exc:  # noqa: BLE001 - the diagnostic endpoint must survive config callback failures.
        config_diagnostic_error = _diagnostic_error("CONFIG_SNAPSHOT_FAILED", exc)
        logger.error("Provider registry configuration snapshot failed: %s", config_diagnostic_error)
        config = {}
    if not isinstance(config, Mapping):
        config_diagnostic_error = "CONFIG_SNAPSHOT_INVALID: expected mapping"
        logger.error("Provider registry configuration snapshot was not a mapping")
        config = {}

    llm = _section(config, "llm")
    tts = _section(config, "tts")
    asr = _section(config, "asr")
    vision_enabled = bool(llm.get("vision_enabled", False))
    specs = (
        {
            "id": "llm",
            "kind": "llm",
            "label": "对话模型",
            "section": llm,
            "optional": False,
            "capabilities": ["chat", "streaming"],
            "configured": bool(str(llm.get("provider") or "").strip() and (str(llm.get("model") or "").strip() or str(llm.get("base_url") or "").strip())),
        },
        {
            "id": "vision",
            "kind": "vision",
            "label": "视觉模型",
            "section": llm,
            "optional": True,
            "capabilities": ["image-understanding"],
            "configured": vision_enabled and bool(str(llm.get("vision_provider") or "").strip() and (str(llm.get("vision_model") or "").strip() or str(llm.get("vision_base_url") or "").strip())),
        },
        {
            "id": "tts",
            "kind": "tts",
            "label": "语音合成",
            "section": tts,
            "optional": True,
            "capabilities": ["speech-synthesis"],
            "configured": bool(str(tts.get("provider") or "").strip() and (str(tts.get("model") or "").strip() or str(tts.get("genie_character") or "").strip() or str(tts.get("base_url") or "").strip())),
        },
        {
            "id": "asr",
            "kind": "asr",
            "label": "语音识别",
            "section": asr,
            "optional": True,
            "capabilities": ["speech-recognition", "streaming"],
            "configured": bool(str(asr.get("provider") or "").strip() and str(asr.get("provider") or "").strip().lower() not in {"none", "disabled"}),
        },
    )

    async def project(spec: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = str(spec["id"])
        section = spec["section"]
        client = None
        client_diagnostic_error: str | None = None
        client_provider = client_providers.get(provider_id)
        if client_provider is not None:
            try:
                client = client_provider()
            except Exception as exc:  # noqa: BLE001 - client factories are provider-defined boundaries.
                client_diagnostic_error = _diagnostic_error("CLIENT_PROVIDER_FAILED", exc)
                logger.error(
                    "Provider registry client lookup failed for %s: %s",
                    provider_id,
                    client_diagnostic_error,
                )
                client = None
        configured = bool(spec["configured"])
        available = client is not None
        healthy, message = await _probe_health(health_providers.get(provider_id), available)
        diagnostic_error = client_diagnostic_error or config_diagnostic_error
        if client_diagnostic_error is not None:
            message = "Provider runtime lookup failed"
            healthy = False
        elif config_diagnostic_error is not None:
            message = "Provider configuration status unavailable"
            healthy = False
        elif not configured:
            message = "未配置" if provider_id != "vision" or not vision_enabled else "视觉模型未配置"
            healthy = False
        elif not available and provider_id in {"llm", "tts", "vision", "asr"}:
            message = "已配置但运行时未初始化"
            healthy = False
        model_key = "vision_model" if provider_id == "vision" else "model"
        provider_key = "vision_provider" if provider_id == "vision" else "provider"
        return {
            "id": provider_id,
            "kind": spec["kind"],
            "label": spec["label"],
            "provider": str(section.get(provider_key) or "") or None,
            "model": str(section.get(model_key) or "") or None,
            "configured": configured,
            "available": available,
            "healthy": healthy,
            "retryable": configured and not healthy,
            "optional": bool(spec["optional"]),
            "capabilities": list(spec["capabilities"]),
            "message": _safe_message(message, "状态未知"),
            "diagnosticError": diagnostic_error,
            "source": "runtime+config",
        }

    providers = list(await asyncio.gather(*(project(spec) for spec in specs)))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "providers": providers,
        "summary": {
            "total": len(providers),
            "configured": sum(1 for item in providers if item["configured"]),
            "available": sum(1 for item in providers if item["available"]),
            "healthy": sum(1 for item in providers if item["healthy"]),
            "requiredHealthy": all(item["healthy"] for item in providers if not item["optional"]),
        },
    }


__all__ = ["HEALTH_PROBE_TIMEOUT_SECONDS", "SCHEMA_VERSION", "build_provider_registry_snapshot"]

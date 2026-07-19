from __future__ import annotations

import importlib.util
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

DISCOVERY_TIMEOUT_SECONDS = 0.35


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_urls(value: str | None) -> list[str]:
    return [item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _with_scheme(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return raw
    return raw if "://" in raw else f"http://{raw}"


def _openai_base_url(value: str) -> str:
    raw = _with_scheme(value).rstrip("/")
    if raw.endswith("/v1"):
        return raw
    return f"{raw}/v1"


def _env_url_candidates(env_names: tuple[str, ...], defaults: list[str], *, openai_compatible: bool = False) -> list[str]:
    values: list[str] = []
    for env_name in env_names:
        values.extend(_split_urls(os.getenv(env_name)))
    if openai_compatible:
        values = [_openai_base_url(value) for value in values]
    else:
        values = [_with_scheme(value) for value in values]
    return _dedupe([*values, *defaults])


def _models_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _collections_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/collections"


def _tcp_open(base_url: str, timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> bool:
    try:
        parsed = urlparse(_with_scheme(base_url))
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _extract_openai_models(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [
                str(item.get("id") or item.get("name") or "").strip()
                for item in data
                if isinstance(item, dict) and str(item.get("id") or item.get("name") or "").strip()
            ]
        models = payload.get("models")
        if isinstance(models, list):
            return [
                str(item.get("name") or item.get("model") or item.get("id") or item).strip()
                for item in models
                if str(item.get("name") or item.get("model") or item.get("id") or item).strip()
            ]
    if isinstance(payload, list):
        return [str(item.get("id") or item.get("name") or item).strip() for item in payload if str(item).strip()]
    return []


async def _probe_json(url: str, timeout: float) -> tuple[bool, int | None, Any, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.get(url)
        if response.status_code >= 500:
            return False, response.status_code, None, f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return response.status_code < 500, response.status_code, payload, "ok"
    except Exception as exc:
        return False, None, None, str(exc)


async def _discover_llm(timeout: float) -> list[dict[str, object]]:
    specs = [
        {
            "id": "ollama",
            "label": "Ollama",
            "provider": "ollama",
            "urls": _env_url_candidates(
                ("YUIZAKI_OLLAMA_BASE_URL", "OLLAMA_BASE_URL", "OLLAMA_HOST"),
                ["http://127.0.0.1:11434/v1", "http://localhost:11434/v1"],
                openai_compatible=True,
            ),
        },
        {
            "id": "lmstudio",
            "label": "LM Studio",
            "provider": "lmstudio",
            "urls": _env_url_candidates(
                ("YUIZAKI_LM_STUDIO_BASE_URL", "LM_STUDIO_BASE_URL", "LMSTUDIO_BASE_URL"),
                ["http://127.0.0.1:1234/v1", "http://localhost:1234/v1"],
                openai_compatible=True,
            ),
        },
    ]
    results: list[dict[str, object]] = []
    for spec in specs:
        for base_url in spec["urls"]:
            ok, status_code, payload, message = await _probe_json(_models_url(str(base_url)), timeout)
            models = _extract_openai_models(payload)
            tcp_ok = ok or _tcp_open(str(base_url), timeout)
            results.append({
                "id": spec["id"],
                "label": spec["label"],
                "provider": spec["provider"],
                "base_url": base_url,
                "ok": tcp_ok,
                "status_code": status_code,
                "models": models,
                "message": "models detected" if models else ("service reachable" if tcp_ok else message),
            })
    return results


async def _discover_asr(timeout: float) -> list[dict[str, object]]:
    urls = _env_url_candidates(
        ("YUIZAKI_ASR_BASE_URL", "ASR_BASE_URL", "YUIZAKI_SENSEVOICE_BASE_URL"),
        ["http://127.0.0.1:8899/v1", "http://localhost:8899/v1"],
        openai_compatible=True,
    )
    results: list[dict[str, object]] = []
    for base_url in urls:
        ok, status_code, _payload, message = await _probe_json(_models_url(base_url), timeout)
        tcp_ok = ok or _tcp_open(base_url, timeout)
        results.append({
            "id": "sensevoice-service",
            "label": "SenseVoice / FunASR",
            "provider": "sensevoice-service",
            "base_url": base_url,
            "ok": tcp_ok,
            "status_code": status_code,
            "message": "service reachable" if tcp_ok else message,
        })
    return results


def _discover_tts() -> list[dict[str, object]]:
    default_cache = _backend_root() / ".cache" / "GenieData" / "GenieData"
    configured_cache = Path(os.getenv("GENIE_DATA_DIR", "")).expanduser() if os.getenv("GENIE_DATA_DIR") else default_cache
    model_dirs = _dedupe([
        *(str(Path(item).expanduser()) for item in _split_urls(os.getenv("YUIZAKI_GENIE_MODEL_DIRS"))),
        str(configured_cache),
    ])
    installed = importlib.util.find_spec("genie_tts") is not None
    results: list[dict[str, object]] = []
    for model_dir in model_dirs:
        model_dir_exists = Path(model_dir).exists()
        results.append({
            "id": "genie-tts",
            "label": "Genie TTS",
            "provider": "genie-tts",
            "ok": installed or model_dir_exists,
            "installed": installed,
            "model_dir": model_dir,
            "model_dir_exists": model_dir_exists,
            "message": "library installed" if installed else ("model directory found" if model_dir_exists else "not found"),
        })
    return results


async def _discover_svc(timeout: float) -> list[dict[str, object]]:
    urls = _env_url_candidates(
        ("YUIZAKI_SVC_BASE_URL", "SVC_BASE_URL", "SOULX_BASE_URL"),
        ["http://127.0.0.1:7861", "http://localhost:7861"],
    )
    return [
        {
            "id": "soulx-service",
            "label": "SoulX-Singer-SVC",
            "provider": "soulx-service",
            "base_url": base_url,
            "ok": _tcp_open(base_url, timeout),
            "message": "service reachable" if _tcp_open(base_url, timeout) else "not listening",
        }
        for base_url in urls
    ]


async def _discover_memory(timeout: float) -> list[dict[str, object]]:
    urls = _env_url_candidates(
        ("YUIZAKI_QDRANT_URL", "QDRANT_URL"),
        ["http://127.0.0.1:6333", "http://localhost:6333"],
    )
    results: list[dict[str, object]] = []
    for base_url in urls:
        ok, status_code, _payload, message = await _probe_json(_collections_url(base_url), timeout)
        tcp_ok = ok or _tcp_open(base_url, timeout)
        results.append({
            "id": "qdrant",
            "label": "Qdrant",
            "backend": "qdrant",
            "qdrant_url": base_url,
            "ok": tcp_ok,
            "status_code": status_code,
            "message": "service reachable" if tcp_ok else message,
        })
    return results


async def discover_local_runtime_candidates(timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> dict[str, object]:
    return {
        "llm": await _discover_llm(timeout),
        "asr": await _discover_asr(timeout),
        "tts": _discover_tts(),
        "svc": await _discover_svc(timeout),
        "memory": await _discover_memory(timeout),
    }

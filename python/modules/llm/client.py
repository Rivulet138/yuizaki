"""
LLM client module for streaming chat completions.
Handles OpenAI-compatible API calls with token streaming.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any, AsyncIterator, NoReturn, Optional

import httpx

from ..core.config import config
from ..core.state import Generation, GenerationManager
from ..system.voice_diagnostics import VoiceDiagnostics
from .providers import (
    build_llm_auth_headers,
    is_claude_provider,
    llm_protocol,
    llm_request_url,
    llm_chat_url,
    llm_models_url,
    normalize_llm_base_url,
    normalize_llm_provider,
)
from .context_window import build_and_truncate_layered_context, message_content_to_text
from .capabilities import get_model_limits
from ..pet_control import (
    build_pet_control_response_format,
    extract_pet_control_payload,
    filter_pet_control_payload,
    IncrementalJsonReplyDecoder,
    merge_messages_with_pet_control_prompt,
)

logger = logging.getLogger("yuizaki.llm")

_EMPTY_REASONING_RETRY_MIN_TOKENS = 256
_OPTIONAL_GENERATION_FIELDS = (
    "thinking",
    "reasoning_effort",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "frequency_penalty",
    "presence_penalty",
    "repetition_penalty",
)
_NEUTRAL_GENERATION_VALUES = {
    "top_k": 0.0,
    "min_p": 0.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
}
_GENERATION_COMPAT_MAX_RETRIES = len(_OPTIONAL_GENERATION_FIELDS) + 1
_PRECONNECT_COOLDOWN_SECONDS = 30.0
_PRECONNECT_TIMEOUT_SECONDS = 3.0
_STRUCTURED_OUTPUT_FIELD_MARKERS = ("response_format", "json_schema", "strict", "schema")
_UNSUPPORTED_FIELD_MARKERS = (
    "unsupported",
    "not support",
    "not supported",
    "unrecognized",
    "unknown",
    "extra inputs",
    "extra_forbidden",
    "not permitted",
    "unavailable",
    "not available",
    "invalid parameter",
)
_UNSUPPORTED_MULTIMODAL_MARKERS = (
    "image",
    "image_url",
    "vision",
    "visual",
    "multimodal",
    "multi-modal",
    "content type",
    "content block",
    "base64",
)
_GENERIC_GENERATION_FIELD_MARKERS = (
    "parameter",
    "param",
    "field",
    "extra input",
    "extra_forbidden",
    "not permitted",
)
_SECRET_TEXT_PATTERNS = (
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer <redacted>",
    ),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(?:Bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;}\]]+"),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)([\"'](?:api[_-]?key|token|secret|password)[\"']\s*:\s*[\"'])[^\"']+([\"'])"),
        r"\1<redacted>\2",
    ),
    (
        re.compile(r"\b(?:sk|sk-proj|sess|qk)-[A-Za-z0-9_-]{8,}\b"),
        "<redacted>",
    ),
)


def normalize_openai_base_url(base_url: str) -> str:
    return normalize_llm_base_url(base_url, "custom")


def _response_excerpt(response: httpx.Response, limit: int = 500) -> str:
    try:
        return response.text[:limit] if response.text else ""
    except httpx.ResponseNotRead:
        return "<stream response body not read>"


def redact_error_text(text: str, limit: int | None = None) -> str:
    redacted = str(text or "")
    for pattern, replacement in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    if limit is not None:
        return redacted[:limit]
    return redacted


def _safe_response_excerpt(response: httpx.Response, limit: int = 500) -> str:
    return redact_error_text(_response_excerpt(response, limit=limit), limit=limit)


def _raise_llm_http_error(exc: httpx.HTTPStatusError, *, context: str) -> NoReturn:
    body_text = _safe_response_excerpt(exc.response)
    logger.error(
        "%s HTTP %d: %s",
        context,
        exc.response.status_code,
        body_text,
    )
    raise RuntimeError(f"LLM API {exc.response.status_code}: {body_text}") from exc


def _mentions_field(text: str, field: str) -> bool:
    field_text = field.lower()
    variants = {
        field_text,
        field_text.replace("_", " "),
        f'"{field_text}"',
        f"'{field_text}'",
    }
    return any(variant in text for variant in variants)


def _looks_like_unsupported_field_error(text: str) -> bool:
    return any(marker in text for marker in _UNSUPPORTED_FIELD_MARKERS)


def _looks_like_generic_generation_field_error(text: str) -> bool:
    return any(marker in text for marker in _GENERIC_GENERATION_FIELD_MARKERS)


def _generation_compat_retry_body(body: dict[str, Any], response_text: str) -> dict[str, Any] | None:
    """Return a safer OpenAI-compatible payload when a provider rejects optional knobs."""
    text = response_text.lower()
    if not _looks_like_unsupported_field_error(text):
        return None

    retry_body = dict(body)
    changed_fields: list[str] = []

    for field in _OPTIONAL_GENERATION_FIELDS:
        if field in retry_body and _mentions_field(text, field):
            retry_body.pop(field, None)
            changed_fields.append(field)

    if (
        not changed_fields
        and _looks_like_generic_generation_field_error(text)
        and any(field in retry_body for field in _OPTIONAL_GENERATION_FIELDS)
    ):
        for field in _OPTIONAL_GENERATION_FIELDS:
            if field in retry_body:
                retry_body.pop(field, None)
                changed_fields.append(field)

    if "max_tokens" in retry_body and _mentions_field(text, "max_tokens"):
        value = retry_body.pop("max_tokens")
        if "max_completion_tokens" in text:
            retry_body["max_completion_tokens"] = value
            changed_fields.append("max_tokens->max_completion_tokens")
        else:
            changed_fields.append("max_tokens")

    if not changed_fields:
        return None

    logger.warning(
        "Retrying LLM request after upstream rejected generation field(s): %s",
        ", ".join(changed_fields),
    )
    return retry_body


def _structured_output_compat_retry_body(body: dict[str, Any], response_text: str) -> dict[str, Any] | None:
    """Return payload without strict structured output when the provider rejects it."""
    if "response_format" not in body:
        return None
    text = response_text.lower()
    if not _looks_like_unsupported_field_error(text):
        return None
    if not any(_mentions_field(text, field) for field in _STRUCTURED_OUTPUT_FIELD_MARKERS):
        return None

    retry_body = dict(body)
    retry_body.pop("response_format", None)
    logger.warning(
        "Retrying LLM request without structured response_format after upstream rejection: %s",
        redact_error_text(response_text, limit=240),
    )
    return retry_body


def _content_has_multimodal_blocks(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, Mapping) and block.get("type") in {"image_url", "image", "input_image"}
        for block in content
    )


def _messages_have_multimodal_blocks(messages: Any) -> bool:
    if not isinstance(messages, list):
        return False
    return any(
        isinstance(message, Mapping) and _content_has_multimodal_blocks(message.get("content"))
        for message in messages
    )


def _looks_like_unsupported_multimodal_error(text: str) -> bool:
    lowered = text.lower()
    if not any(marker in lowered for marker in _UNSUPPORTED_MULTIMODAL_MARKERS):
        return False
    return _looks_like_unsupported_field_error(lowered) or any(
        marker in lowered
        for marker in ("invalid", "not allowed", "only supported", "not compatible")
    )


def _strip_multimodal_content(content: Any) -> str:
    text = message_content_to_text(content).strip()
    notice = (
        "[Live screen frame omitted: the configured model or provider rejected image input. "
        "Do not infer visual details from pixels in this response.]"
    )
    return f"{text}\n\n{notice}".strip() if text else notice


def _multimodal_compat_retry_body(body: dict[str, Any], response_text: str) -> dict[str, Any] | None:
    if not _looks_like_unsupported_multimodal_error(response_text):
        return None
    messages = body.get("messages")
    if not _messages_have_multimodal_blocks(messages):
        return None

    retry_body = dict(body)
    retry_messages: list[dict[str, Any]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, Mapping):
            continue
        next_message = dict(message)
        content = next_message.get("content")
        if _content_has_multimodal_blocks(content):
            next_message["content"] = _strip_multimodal_content(content)
        retry_messages.append(next_message)
    retry_body["messages"] = retry_messages
    logger.warning(
        "Retrying LLM request without image content after upstream rejected multimodal input: %s",
        redact_error_text(response_text, limit=240),
    )
    return retry_body


def _apply_pet_control_response_format(body: dict[str, Any], pet_control_context: Optional[dict[str, Any]]) -> None:
    if pet_control_context:
        body["response_format"] = build_pet_control_response_format(pet_control_context)


def _openai_image_url_to_claude_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_image_url = block.get("image_url") or block.get("input_image")
    url = ""
    if isinstance(raw_image_url, Mapping):
        url = str(raw_image_url.get("url") or raw_image_url.get("image_url") or "")
    elif isinstance(raw_image_url, str):
        url = raw_image_url
    if not url:
        return None

    data_url_match = re.match(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", url, flags=re.DOTALL)
    if data_url_match:
        media_type, data = data_url_match.groups()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _message_content_to_claude_content(content: Any) -> str | list[dict[str, Any]]:
    if not isinstance(content, list):
        return message_content_to_text(content)

    image_blocks: list[dict[str, Any]] = []
    text_blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type in {"image_url", "input_image"}:
            image_block = _openai_image_url_to_claude_block(block)
            if image_block is not None:
                image_blocks.append(image_block)
        elif block_type == "image":
            image_blocks.append(dict(block))
        elif block_type == "text":
            text = str(block.get("text") or "").strip()
            if text:
                text_blocks.append({"type": "text", "text": text})

    converted = [*image_blocks, *text_blocks]
    if converted:
        return converted
    return message_content_to_text(content)


def _openai_block_to_gemini_part(block: Mapping[str, Any]) -> dict[str, Any] | None:
    block_type = block.get("type")
    if block_type == "text":
        text = str(block.get("text") or "")
        return {"text": text} if text else None
    if block_type not in {"image_url", "input_image"}:
        return None
    raw_image = block.get("image_url") or block.get("input_image")
    url = raw_image.get("url") if isinstance(raw_image, Mapping) else raw_image
    if not isinstance(url, str):
        return None
    match = re.match(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", url, flags=re.DOTALL)
    if match:
        mime_type, data = match.groups()
        return {"inlineData": {"mimeType": mime_type, "data": data}}
    if url.startswith(("http://", "https://")):
        return {"fileData": {"mimeType": "image/*", "fileUri": url}}
    return None


def _message_content_to_gemini_parts(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        text = message_content_to_text(content)
        return [{"text": text}] if text else []
    parts: list[dict[str, Any]] = []
    for raw_block in content:
        if isinstance(raw_block, Mapping):
            part = _openai_block_to_gemini_part(raw_block)
            if part is not None:
                parts.append(part)
    return parts


def _messages_to_gemini_payload(body: dict[str, Any]) -> dict[str, Any]:
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    for message in body.get("messages") or []:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "user")
        parts = _message_content_to_gemini_parts(message.get("content"))
        if role == "system":
            system_parts.extend(parts)
            continue
        if role == "tool":
            tool_text = message_content_to_text(message.get("content"))
            parts = [{"text": tool_text}] if tool_text else []
            role = "user"
        if role == "assistant":
            role = "model"
        if parts:
            contents.append({"role": role if role in {"user", "model"} else "user", "parts": parts})

    generation_config: dict[str, Any] = {}
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "topP"),
        ("top_k", "topK"),
        ("max_tokens", "maxOutputTokens"),
    ):
        if body.get(source) is not None:
            generation_config[target] = body[source]
    payload: dict[str, Any] = {"contents": contents or [{"role": "user", "parts": [{"text": "ping"}]}]}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    if generation_config:
        payload["generationConfig"] = generation_config
    tools: list[dict[str, Any]] = []
    for tool in body.get("tools") or []:
        function = tool.get("function") if isinstance(tool, Mapping) else None
        if not isinstance(function, Mapping) or not function.get("name"):
            continue
        tools.append({
            "name": str(function["name"]),
            "description": str(function.get("description") or ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
        })
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    return payload


def _gemini_response_to_chat_completion(data: Mapping[str, Any]) -> dict[str, Any]:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        if not isinstance(part, Mapping):
            continue
        if part.get("text"):
            text_parts.append(str(part["text"]))
        function_call = part.get("functionCall")
        if isinstance(function_call, Mapping) and function_call.get("name"):
            tool_calls.append({
                "id": f"gemini-call-{index}",
                "type": "function",
                "function": {
                    "name": str(function_call["name"]),
                    "arguments": json.dumps(function_call.get("args") or {}, ensure_ascii=False),
                },
            })
    return {"choices": [{"message": {"content": "".join(text_parts), "tool_calls": tool_calls}}]}


async def _iter_gemini_text_deltas(resp: httpx.Response) -> AsyncIterator[str]:
    async for raw_line in resp.aiter_lines():
        data_str = _parse_sse_data(raw_line)
        if data_str is None:
            continue
        data = json.loads(data_str)
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        for part in parts:
            if isinstance(part, Mapping) and part.get("text"):
                yield str(part["text"])


def _messages_to_claude_payload(body: dict[str, Any]) -> dict[str, Any]:
    system_parts: list[str] = []
    claude_messages: list[dict[str, Any]] = []
    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "system":
            content_text = message_content_to_text(content)
            if content_text:
                system_parts.append(content_text)
            continue
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if not tool_call_id:
                continue
            claude_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": message_content_to_text(content),
                }],
            })
            continue

        claude_content = _message_content_to_claude_content(content)
        if role == "assistant" and isinstance(message.get("tool_calls"), list):
            blocks: list[dict[str, Any]] = []
            if isinstance(claude_content, str) and claude_content.strip():
                blocks.append({"type": "text", "text": claude_content.strip()})
            elif isinstance(claude_content, list):
                blocks.extend(block for block in claude_content if isinstance(block, dict))
            for tool_call in message["tool_calls"]:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                if not isinstance(function, dict):
                    continue
                name = str(function.get("name") or "").strip()
                tool_use_id = str(tool_call.get("id") or "").strip()
                if not name or not tool_use_id:
                    continue
                raw_arguments = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except json.JSONDecodeError:
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": name,
                    "input": arguments,
                })
            claude_content = blocks
        if isinstance(claude_content, str):
            claude_content = claude_content.strip()
        if not claude_content:
            continue
        if role == "assistant":
            claude_role = "assistant"
        else:
            claude_role = "user"
        claude_messages.append({"role": claude_role, "content": claude_content})

    payload: dict[str, Any] = {
        "model": body.get("model"),
        "messages": claude_messages or [{"role": "user", "content": "ping"}],
        "max_tokens": int(body.get("max_tokens") or body.get("max_completion_tokens") or config.llm.default_max_output_tokens or 2048),
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if "temperature" in body:
        payload["temperature"] = body["temperature"]
    if "top_p" in body:
        payload["top_p"] = body["top_p"]
    tools: list[dict[str, Any]] = []
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        input_schema = function.get("parameters")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        converted: dict[str, Any] = {"name": name, "input_schema": input_schema}
        description = str(function.get("description") or "").strip()
        if description:
            converted["description"] = description
        tools.append(converted)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = {"type": "auto"}
    return payload


def _claude_text_from_response(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "".join(parts).strip()


def _claude_response_to_chat_completion(data: dict[str, Any]) -> dict[str, Any]:
    tool_calls: list[dict[str, Any]] = []
    for item in data.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = str(item.get("name") or "").strip()
        tool_use_id = str(item.get("id") or "").strip()
        if not name or not tool_use_id:
            continue
        tool_input = item.get("input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        tool_calls.append({
            "id": tool_use_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(tool_input, ensure_ascii=False, separators=(",", ":")),
            },
        })
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": _claude_text_from_response(data),
                "tool_calls": tool_calls,
            },
        }],
        "raw_provider_response": data,
    }


def extract_model_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raw_models = payload.get("models")
    else:
        raw_models = payload
    if not isinstance(raw_models, list):
        return []

    ids: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        model_id = ""
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
        elif isinstance(item, str):
            model_id = item.strip()
        if model_id and model_id not in seen:
            seen.add(model_id)
            ids.append(model_id)
    return ids


async def fetch_available_models(base_url: str, api_key: str = "", timeout: float = 30.0, provider: str = "custom") -> list[str]:
    provider = normalize_llm_provider(provider, base_url)
    endpoint = normalize_llm_base_url(base_url, provider)
    if not endpoint:
        raise ValueError("LLM Base URL is required")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(llm_models_url(endpoint, provider), headers=build_llm_auth_headers(api_key, provider))
        resp.raise_for_status()
        return extract_model_ids(resp.json())


def _build_summary_rewrite_messages(source_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是会话摘要器。请将给定内容重写为简洁、结构化的长期摘要。"
                "要求：保留用户偏好、事实、近期目标、未完成事项；删除寒暄与重复。"
                "输出 6-12 行要点，中文，避免编造。"
            ),
        },
        {
            "role": "user",
            "content": source_text,
        },
    ]


async def _rewrite_summary_with_llm(
    http_client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    source_text: str,
    provider: str = "custom",
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _build_summary_rewrite_messages(source_text),
        "stream": False,
        "max_tokens": 320,
        "temperature": 0.2,
    }
    claude_provider = is_claude_provider(provider)
    native_gemini = llm_protocol(provider, base_url) == "gemini-generate-content"
    resp = await http_client.post(
        llm_request_url(base_url, provider, model=model),
        json=(
            _messages_to_claude_payload(payload)
            if claude_provider
            else _messages_to_gemini_payload(payload)
            if native_gemini
            else payload
        ),
        headers=headers,
    )
    resp.raise_for_status()
    raw_data = resp.json()
    data = (
        _claude_response_to_chat_completion(raw_data)
        if claude_provider
        else _gemini_response_to_chat_completion(raw_data)
        if native_gemini
        else raw_data
    )
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def _build_quality_score_messages(summary_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是摘要质量评分器。请根据摘要内容输出 JSON，字段为 overall/facts/preferences/goals_open_tasks，"
                "值范围 0-100，整数。只输出 JSON，不要解释。"
            ),
        },
        {
            "role": "user",
            "content": "请评分：\n" + (summary_text or ""),
        },
    ]


async def _score_summary_with_llm(
    http_client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    summary_text: str,
    provider: str = "custom",
) -> Optional[dict[str, int]]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _build_quality_score_messages(summary_text),
        "stream": False,
        "max_tokens": 120,
        "temperature": 0.0,
    }
    claude_provider = is_claude_provider(provider)
    native_gemini = llm_protocol(provider, base_url) == "gemini-generate-content"
    resp = await http_client.post(
        llm_request_url(base_url, provider, model=model),
        json=(
            _messages_to_claude_payload(payload)
            if claude_provider
            else _messages_to_gemini_payload(payload)
            if native_gemini
            else payload
        ),
        headers=headers,
    )
    resp.raise_for_status()
    raw_data = resp.json()
    data = (
        _claude_response_to_chat_completion(raw_data)
        if claude_provider
        else _gemini_response_to_chat_completion(raw_data)
        if native_gemini
        else raw_data
    )
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    content = str(msg.get("content") or "").strip()
    if not content:
        return None

    parsed = json.loads(content)
    keys = ["overall", "facts", "preferences", "goals_open_tasks"]
    if not all(k in parsed for k in keys):
        return None
    return {k: max(0, min(100, int(parsed[k]))) for k in keys}


def _parse_sse_data(line: str) -> Optional[str]:
    """Parse SSE data line. Returns the JSON string or None."""
    if not line.startswith("data:"):
        return None
    data_str = line[5:].strip()
    if data_str == "[DONE]":
        return None
    return data_str


async def _iter_claude_text_deltas(resp: httpx.Response) -> AsyncIterator[str]:
    """Yield text deltas from Anthropic Messages API SSE events."""
    async for raw_line in resp.aiter_lines():
        data_str = _parse_sse_data(raw_line)
        if data_str is None:
            continue

        event = json.loads(data_str)
        event_type = event.get("type")
        if event_type == "content_block_delta":
            delta = event.get("delta") or {}
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if text:
                    yield str(text)
        elif event_type == "error":
            error = event.get("error") or {}
            if isinstance(error, dict):
                message = error.get("message") or error.get("type") or error
            else:
                message = error
            raise RuntimeError(f"Claude stream error: {message}")


def _clean_model_override(model: Optional[str]) -> str | None:
    value = str(model or "").strip()
    return value or None


def _clean_reasoning_effort(reasoning_effort: Optional[str]) -> str | None:
    value = str(reasoning_effort or "").strip().lower()
    if value in {"", "default", "none"}:
        return None
    if value in {"minimal", "low", "medium", "high", "max", "xhigh", "auto"}:
        return value
    return None


def _clean_thinking_mode(thinking: Optional[str]) -> str | None:
    value = str(thinking or "").strip().lower()
    return value if value in {"enabled", "disabled"} else None


def _apply_generation_options(
    body: dict[str, Any],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    min_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    reasoning_effort: Optional[str] = None,
    thinking: Optional[str] = None,
) -> None:
    model_override = _clean_model_override(model)
    if model_override:
        body["model"] = model_override
    if temperature is not None:
        body["temperature"] = float(temperature)
    if top_p is not None:
        body["top_p"] = float(top_p)
    _apply_optional_generation_number(body, "top_k", top_k, integer=True)
    _apply_optional_generation_number(body, "min_p", min_p)
    _apply_optional_generation_number(body, "frequency_penalty", frequency_penalty)
    _apply_optional_generation_number(body, "presence_penalty", presence_penalty)
    _apply_optional_generation_number(body, "repetition_penalty", repetition_penalty)
    clean_reasoning = _clean_reasoning_effort(reasoning_effort)
    if clean_reasoning:
        body["reasoning_effort"] = clean_reasoning
    clean_thinking = _clean_thinking_mode(thinking)
    if clean_thinking:
        body["thinking"] = {"type": clean_thinking}


def _apply_optional_generation_number(
    body: dict[str, Any],
    field: str,
    value: object,
    *,
    integer: bool = False,
) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float, str)):
        return
    try:
        numeric = float(value)
    except ValueError:
        return
    neutral = _NEUTRAL_GENERATION_VALUES.get(field)
    if neutral is not None and numeric == neutral:
        body.pop(field, None)
        return
    body[field] = int(numeric) if integer else numeric


def _apply_config_generation_defaults(body: dict[str, Any]) -> None:
    body["temperature"] = config.llm.temperature
    body["top_p"] = config.llm.top_p
    _apply_optional_generation_number(body, "top_k", getattr(config.llm, "top_k", None), integer=True)
    _apply_optional_generation_number(body, "min_p", getattr(config.llm, "min_p", None))
    _apply_optional_generation_number(body, "frequency_penalty", getattr(config.llm, "frequency_penalty", None))
    _apply_optional_generation_number(body, "presence_penalty", getattr(config.llm, "presence_penalty", None))
    _apply_optional_generation_number(body, "repetition_penalty", getattr(config.llm, "repetition_penalty", None))


def _effective_model_budget(
    model: str | None,
    requested: int | None,
    configured: int,
    limit_key: str,
    *,
    provider: str | None = None,
    log_clamp: bool = True,
) -> int:
    """Clamp a budget only when the selected model has an explicit registry limit."""
    value = max(1, int(requested if requested is not None else configured))
    effective_provider = provider or config.llm.provider
    limit = get_model_limits(effective_provider, model or config.llm.model).get(limit_key)
    if limit is None:
        return value
    if value > limit and log_clamp:
        logger.warning(
            "Clamping LLM %s from %d to registry limit %d for provider=%s model=%s",
            limit_key,
            value,
            limit,
            effective_provider,
            model or config.llm.model,
        )
    return min(value, limit)


def _should_retry_empty_reasoning_response(data: dict[str, Any], max_output_tokens: Optional[int]) -> bool:
    if max_output_tokens is None or int(max_output_tokens) >= _EMPTY_REASONING_RETRY_MIN_TOKENS:
        return False

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return False

    choice = choices[0]
    if not isinstance(choice, dict):
        return False
    if str(choice.get("finish_reason") or "") != "length":
        return False

    message = choice.get("message")
    if not isinstance(message, dict):
        return False
    if str(message.get("content") or "").strip():
        return False
    if message.get("tool_calls"):
        return False

    reasoning_text = str(
        message.get("reasoning_content")
        or message.get("reasoning")
        or ""
    ).strip()
    return bool(reasoning_text)


async def _safe_send(ws: Any, gen: Generation, msg: dict[str, object]) -> None:
    """Send message to WebSocket, respecting cancellation."""
    if gen.invalidated or gen.cancel.is_set():
        return
    try:
        await ws.send_json(msg)
    except (ConnectionError, OSError, RuntimeError) as e:
        logger.warning("Failed to send WS message: %s", e)


class LLMClient:
    """Provider-aware LLM client with a normalized chat-completion result."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        provider: str = "custom",
        image_detail: str = "auto",
        diagnostics: VoiceDiagnostics | None = None,
    ):
        self.provider = normalize_llm_provider(provider, base_url)
        # Native streaming tool-call framing is provider-specific and is
        # opt-in until an adapter implements the protocol.
        self.streaming_tool_calls_supported = False
        self.base_url = normalize_llm_base_url(base_url, self.provider)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        normalized_detail = str(image_detail or "auto").strip().lower()
        self.image_detail = normalized_detail if normalized_detail in {"low", "high", "auto", "original"} else "auto"
        self.diagnostics = diagnostics or VoiceDiagnostics()
        self._http: Optional[httpx.AsyncClient] = None
        self._tool_calls_supported: bool | None = None
        self._preconnect_lock = asyncio.Lock()
        self._preconnect_task: asyncio.Task[bool] | None = None
        self._preconnect_last_attempt_monotonic: float | None = None
        self._preconnect_last_elapsed_ms: float | None = None
        self._preconnect_last_ok: bool | None = None
        self._preconnect_last_reached_upstream: bool | None = None
        self._preconnect_last_http_status: int | None = None
        self._preconnect_last_error: str | None = None
        self._preconnect_attempts = 0
        self._preconnect_failures = 0

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._http = httpx.AsyncClient(timeout=self.timeout)
        logger.info("LLM client connected to %s (provider=%s)", self.base_url, self.provider)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        preconnect_task = self._preconnect_task
        if preconnect_task is not None and not preconnect_task.done():
            preconnect_task.cancel()
            try:
                await preconnect_task
            except asyncio.CancelledError:
                pass
        self._preconnect_task = None
        if self._http:
            await self._http.aclose()
            self._http = None
            logger.info("LLM client disconnected")

    def _preconnect_cooldown_remaining(self) -> float:
        last_attempt = self._preconnect_last_attempt_monotonic
        if last_attempt is None:
            return 0.0
        return max(0.0, _PRECONNECT_COOLDOWN_SECONDS - (time.monotonic() - last_attempt))

    async def preconnect(self, *, force: bool = False) -> bool:
        """Reach the provider without generating tokens so the HTTP pool is warm."""
        async with self._preconnect_lock:
            http_client = self._http
            if http_client is None:
                return False
            if not force and self._preconnect_cooldown_remaining() > 0:
                return bool(self._preconnect_last_reached_upstream)

            self._preconnect_last_attempt_monotonic = time.monotonic()
            self._preconnect_attempts += 1
            started = time.perf_counter()
            self._preconnect_last_ok = None
            self._preconnect_last_reached_upstream = False
            self._preconnect_last_http_status = None
            self._preconnect_last_error = None
            try:
                response = await http_client.get(
                    llm_models_url(self.base_url, self.provider),
                    headers=build_llm_auth_headers(self.api_key, self.provider),
                    timeout=min(max(float(self.timeout), 0.1), _PRECONNECT_TIMEOUT_SECONDS),
                )
            except asyncio.CancelledError:
                self._preconnect_last_error = "preconnect cancelled"
                raise
            except httpx.RequestError as exc:
                self._preconnect_failures += 1
                self._preconnect_last_ok = False
                self._preconnect_last_error = str(exc)[:240]
                logger.debug("LLM preconnect failed: %s", exc)
                return False
            finally:
                self._preconnect_last_elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

            self._preconnect_last_reached_upstream = True
            self._preconnect_last_http_status = response.status_code
            self._preconnect_last_ok = response.is_success
            logger.debug(
                "LLM preconnect reached provider=%s status=%d elapsed_ms=%.2f",
                self.provider,
                response.status_code,
                self._preconnect_last_elapsed_ms,
            )
            return True

    def schedule_preconnect(self) -> bool:
        """Queue a deduplicated, non-blocking preconnect attempt."""
        if self._http is None or self._preconnect_cooldown_remaining() > 0:
            return False
        current = self._preconnect_task
        if current is not None and not current.done():
            return False

        task = asyncio.create_task(self.preconnect(), name="llm-http-preconnect")
        self._preconnect_task = task

        def _consume_result(done: asyncio.Task[bool]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive task boundary
                logger.warning("Unexpected LLM preconnect failure: %s", exc)

        task.add_done_callback(_consume_result)
        return True

    def status_snapshot(self) -> dict[str, object]:
        """Return transport diagnostics without exposing credentials or prompts."""
        model_limits = get_model_limits(self.provider, self.model)
        return {
            "available": self._http is not None,
            "provider": self.provider,
            "protocol": llm_protocol(self.provider, self.base_url),
            "model": self.model,
            "model_limits": model_limits,
            "effective_context_max_tokens": _effective_model_budget(
                self.model,
                None,
                int(config.llm.context_max_tokens),
                "context_window_tokens",
                provider=self.provider,
                log_clamp=False,
            ),
            "effective_default_max_output_tokens": _effective_model_budget(
                self.model,
                None,
                int(config.llm.default_max_output_tokens),
                "max_output_tokens",
                provider=self.provider,
                log_clamp=False,
            ),
            "preconnect_running": bool(self._preconnect_task and not self._preconnect_task.done()),
            "preconnect_cooldown_seconds": _PRECONNECT_COOLDOWN_SECONDS,
            "preconnect_cooldown_remaining_ms": round(self._preconnect_cooldown_remaining() * 1000, 2),
            "preconnect_attempts": self._preconnect_attempts,
            "preconnect_failures": self._preconnect_failures,
            "last_preconnect_elapsed_ms": self._preconnect_last_elapsed_ms,
            "last_preconnect_ok": self._preconnect_last_ok,
            "last_preconnect_reached_upstream": self._preconnect_last_reached_upstream,
            "last_preconnect_http_status": self._preconnect_last_http_status,
            "last_preconnect_error": self._preconnect_last_error,
        }

    async def stream_chat(
        self,
        ws: Any,
        gen: Generation,
        mgr: GenerationManager,
        messages: list[dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        pet_control_context: Optional[dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        repetition_penalty: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        thinking: Optional[str] = None,
    ) -> None:
        """
        Stream chat completion from LLM.
        Accumulates tokens, saves to history, and triggers TTS on completion.
        """
        if not self._http:
            logger.error("LLM client not connected")
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": gen.session_id,
                "generation_id": gen.generation_id,
                "error": "LLM client not initialized",
            })
            return

        sid, gid = gen.session_id, gen.generation_id
        stream_started_at = time.monotonic()

        headers = build_llm_auth_headers(self.api_key, self.provider)

        body: dict[str, Any] = {
            "model": self.model,
            "stream": True,
        }
        _apply_config_generation_defaults(body)
        _apply_generation_options(
            body,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            repetition_penalty=repetition_penalty,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )
        selected_model = str(model or self.model or "").strip()
        effective_output_tokens = _effective_model_budget(
            selected_model,
            max_output_tokens,
            int(config.llm.default_max_output_tokens),
            "max_output_tokens",
            provider=self.provider,
        )
        body["max_tokens"] = effective_output_tokens
        if not is_claude_provider(self.provider):
            _apply_pet_control_response_format(body, pet_control_context)

        # Week 2: apply context window governance before request.
        context_max_tokens = _effective_model_budget(
            selected_model,
            None,
            int(config.llm.context_max_tokens),
            "context_window_tokens",
            provider=self.provider,
        )
        reserve_tokens = effective_output_tokens
        summary_text = mgr.get_summary(sid)
        windowed_messages, stats = build_and_truncate_layered_context(
            messages=messages,
            max_context_tokens=context_max_tokens,
            reserved_output_tokens=reserve_tokens,
            summary_text=summary_text,
        )
        body["messages"] = merge_messages_with_pet_control_prompt(windowed_messages, pet_control_context)

        # Periodic LLM summary rewrite for long sessions.
        # Run in background with a tight timeout to avoid delaying first token.
        if mgr.should_rewrite_summary(sid):
            async def _background_rewrite() -> None:
                try:
                    await asyncio.wait_for(
                        self.rewrite_session_summary(mgr, sid, source="auto"),
                        timeout=1.2,
                    )
                except asyncio.TimeoutError:
                    mgr.record_summary_audit(sid, source="auto", outcome="timeout", detail="background timeout")
                    logger.warning("[%s/%s] summary rewrite timeout", sid, gid)
                except Exception as exc:
                    mgr.record_summary_audit(sid, source="auto", outcome="error", detail=str(exc))
                    logger.warning("[%s/%s] summary rewrite failed: %s", sid, gid, exc)

            asyncio.create_task(
                _background_rewrite(),
                name=f"summary-rewrite-{sid}-{gid}",
            )

        reply_decoder = IncrementalJsonReplyDecoder() if pet_control_context else None
        raw_stream_parts: list[str] = []
        streamed_reply_parts: list[str] = []
        first_token_recorded = False

        async def _emit_visible_reply(content: str) -> None:
            nonlocal first_token_recorded
            if not content:
                return
            if not first_token_recorded:
                self.diagnostics.record_elapsed(
                    "first_token",
                    stream_started_at,
                    provider=self.provider,
                    request_id=gid,
                )
                first_token_recorded = True
            gen.mark("llm_first_token")
            gen.tokens.append(content)
            streamed_reply_parts.append(content)
            await _safe_send(ws, gen, {
                "type": "token",
                "session_id": sid,
                "generation_id": gid,
                "content": content,
            })

        async def _consume_stream_content(content: str) -> None:
            raw_stream_parts.append(content)
            visible = reply_decoder.feed(content) if reply_decoder is not None else content
            await _emit_visible_reply(visible)

        async def _reconcile_final_reply(final_reply: str) -> None:
            streamed_reply = "".join(streamed_reply_parts)
            if not final_reply or streamed_reply == final_reply:
                return
            if final_reply.startswith(streamed_reply):
                await _emit_visible_reply(final_reply[len(streamed_reply):])
            elif not streamed_reply:
                await _emit_visible_reply(final_reply)

        if is_claude_provider(self.provider):
            gen.mark("llm_request")
            gen.mark("llm_request_started")
            url = llm_chat_url(self.base_url, self.provider)
            claude_payload = _messages_to_claude_payload(body)
            claude_payload["stream"] = True
            logger.info(
                "[%s/%s] Claude LLM stream start msgs=%d budget=%d used=%d dropped=%d reserve=%d",
                sid,
                gid,
                len(windowed_messages),
                stats.budget_tokens,
                stats.input_tokens,
                stats.dropped_messages,
                reserve_tokens,
            )
            try:
                async with self._http.stream(
                    "POST", url, json=claude_payload, headers=headers,
                ) as resp:
                    resp.raise_for_status()

                    async for content in _iter_claude_text_deltas(resp):
                        if gen.cancel.is_set():
                            logger.info("[%s/%s] interrupted during Claude LLM stream", sid, gid)
                            break

                        await _consume_stream_content(content)

                if gen.cancel.is_set() or gen.invalidated:
                    return

                gen.mark("llm_completed")

                final_reply, pet_control = extract_pet_control_payload("".join(raw_stream_parts))
                pet_control = filter_pet_control_payload(pet_control, pet_control_context)
                await _reconcile_final_reply(final_reply)

                if final_reply:
                    gen.tokens = [final_reply]
                    mgr.append_history(sid, "assistant", final_reply)

                if pet_control:
                    setattr(gen, "pet_control", pet_control)
                    await _safe_send(ws, gen, {
                        "type": "pet_control",
                        "session_id": sid,
                        "generation_id": gid,
                        "pet_control": pet_control,
                    })

                await _safe_send(ws, gen, {
                    "type": "done",
                    "session_id": sid,
                    "generation_id": gid,
                    "content": final_reply,
                })
                logger.info("[%s/%s] Claude LLM stream done chars=%d", sid, gid, len(final_reply))
            except httpx.HTTPStatusError as exc:
                body_text = _safe_response_excerpt(exc.response, limit=300)
                logger.error(
                    "[%s/%s] Claude LLM HTTP %d: %s",
                    sid, gid, exc.response.status_code, body_text,
                )
                await _safe_send(ws, gen, {
                    "type": "error",
                    "session_id": sid,
                    "generation_id": gid,
                    "error": f"LLM API {exc.response.status_code}: {body_text}",
                })
            except (httpx.RequestError, json.JSONDecodeError, RuntimeError) as exc:
                logger.error("[%s/%s] Claude LLM stream error: %s", sid, gid, exc)
                await _safe_send(ws, gen, {
                    "type": "error",
                    "session_id": sid,
                    "generation_id": gid,
                    "error": str(exc),
                })
            return

        if llm_protocol(self.provider, self.base_url) == "gemini-generate-content":
            gen.mark("llm_request")
            gen.mark("llm_request_started")
            url = llm_request_url(self.base_url, self.provider, model=body["model"], stream=True)
            payload = _messages_to_gemini_payload(body)
            # Gemini's native streaming endpoint uses SSE and returns the same
            # candidate/parts envelope for every chunk.
            try:
                async with self._http.stream(
                    "POST", f"{url}?alt=sse", json=payload, headers=headers,
                ) as resp:
                    resp.raise_for_status()
                    async for content in _iter_gemini_text_deltas(resp):
                        if gen.cancel.is_set():
                            break
                        await _consume_stream_content(content)
                if gen.cancel.is_set() or gen.invalidated:
                    return
                gen.mark("llm_completed")
                final_reply, pet_control = extract_pet_control_payload("".join(raw_stream_parts))
                pet_control = filter_pet_control_payload(pet_control, pet_control_context)
                await _reconcile_final_reply(final_reply)
                if final_reply:
                    gen.tokens = [final_reply]
                    mgr.append_history(sid, "assistant", final_reply)
                if pet_control:
                    setattr(gen, "pet_control", pet_control)
                    await _safe_send(ws, gen, {
                        "type": "pet_control",
                        "session_id": sid,
                        "generation_id": gid,
                        "pet_control": pet_control,
                    })
                await _safe_send(ws, gen, {
                    "type": "done",
                    "session_id": sid,
                    "generation_id": gid,
                    "content": final_reply,
                })
            except httpx.HTTPStatusError as exc:
                body_text = _safe_response_excerpt(exc.response, limit=300)
                await _safe_send(ws, gen, {
                    "type": "error",
                    "session_id": sid,
                    "generation_id": gid,
                    "error": f"LLM API {exc.response.status_code}: {body_text}",
                })
            except (httpx.RequestError, json.JSONDecodeError, RuntimeError) as exc:
                await _safe_send(ws, gen, {
                    "type": "error",
                    "session_id": sid,
                    "generation_id": gid,
                    "error": str(exc),
                })
            return

        url = llm_chat_url(self.base_url, self.provider)
        gen.mark("llm_request")
        gen.mark("llm_request_started")
        logger.info(
            "[%s/%s] LLM start msgs=%d budget=%d used=%d dropped=%d reserve=%d",
            sid,
            gid,
            len(windowed_messages),
            stats.budget_tokens,
            stats.input_tokens,
            stats.dropped_messages,
            reserve_tokens,
        )

        request_body = body
        compat_retry_attempts = 0
        try:
            while True:
                try:
                    async with self._http.stream(
                        "POST", url, json=request_body, headers=headers,
                    ) as resp:
                        resp.raise_for_status()

                        async for raw_line in resp.aiter_lines():
                            if gen.cancel.is_set():
                                logger.info("[%s/%s] interrupted during LLM stream", sid, gid)
                                break

                            data_str = _parse_sse_data(raw_line)
                            if data_str is None:
                                continue

                            chunk = json.loads(data_str)
                            choices = chunk.get("choices")
                            if not choices:
                                continue

                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if not content:
                                continue

                            await _consume_stream_content(content)
                    break
                except httpx.HTTPStatusError as exc:
                    body_text = _response_excerpt(exc.response, limit=300)
                    retry_body = None
                    if compat_retry_attempts < _GENERATION_COMPAT_MAX_RETRIES and exc.response.status_code in {400, 422}:
                        retry_body = (
                            _structured_output_compat_retry_body(request_body, body_text)
                            or _generation_compat_retry_body(request_body, body_text)
                            or _multimodal_compat_retry_body(request_body, body_text)
                        )
                    if retry_body is not None:
                        compat_retry_attempts += 1
                        request_body = retry_body
                        continue
                    raise

            # ── post-stream ─────────────────────────────────────────
            if gen.cancel.is_set() or gen.invalidated:
                return

            gen.mark("llm_completed")

            final_reply, pet_control = extract_pet_control_payload("".join(raw_stream_parts))
            pet_control = filter_pet_control_payload(pet_control, pet_control_context)
            await _reconcile_final_reply(final_reply)

            # ── persist assistant reply to history ───────
            if final_reply:
                gen.tokens = [final_reply]
                mgr.append_history(sid, "assistant", final_reply)

            if pet_control:
                setattr(gen, "pet_control", pet_control)
                await _safe_send(ws, gen, {
                    "type": "pet_control",
                    "session_id": sid,
                    "generation_id": gid,
                    "pet_control": pet_control,
                })

            await _safe_send(ws, gen, {
                "type": "done",
                "session_id": sid,
                "generation_id": gid,
                "content": final_reply,
            })
            logger.info("[%s/%s] LLM done  chars=%d", sid, gid, len(final_reply))

        except httpx.HTTPStatusError as exc:
            body_text = _safe_response_excerpt(exc.response, limit=300)
            logger.error(
                "[%s/%s] LLM HTTP %d: %s",
                sid, gid, exc.response.status_code, body_text,
            )
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": sid,
                "generation_id": gid,
                "error": f"LLM API {exc.response.status_code}: {body_text}",
            })
        except (httpx.RequestError, json.JSONDecodeError) as exc:
            logger.error("[%s/%s] LLM error: %s", sid, gid, exc)
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": sid,
                "generation_id": gid,
                "error": str(exc),
            })

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_output_tokens: Optional[int] = None,
        pet_control_context: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        repetition_penalty: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        thinking: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self._http:
            raise RuntimeError("LLM client not connected")

        headers = build_llm_auth_headers(self.api_key, self.provider)
        claude_provider = is_claude_provider(self.provider)
        native_gemini = llm_protocol(self.provider, self.base_url) == "gemini-generate-content"

        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": merge_messages_with_pet_control_prompt(messages, pet_control_context),
        }
        _apply_config_generation_defaults(body)
        _apply_generation_options(
            body,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            repetition_penalty=repetition_penalty,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )
        selected_model = str(model or self.model or "").strip()
        effective_output_tokens = _effective_model_budget(
            selected_model,
            max_output_tokens,
            int(config.llm.default_max_output_tokens),
            "max_output_tokens",
            provider=self.provider,
        )
        body["max_tokens"] = effective_output_tokens
        if not claude_provider and not native_gemini:
            _apply_pet_control_response_format(body, pet_control_context)
        request_tools = bool(tools) and self._tool_calls_supported is not False
        if request_tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        url = llm_request_url(self.base_url, self.provider, model=str(body.get("model") or self.model))
        sent_body: dict[str, Any] = body
        active_body: dict[str, Any] = body
        compat_retry_attempts = 0
        tool_retry_used = False
        while True:
            try:
                request_payload = (
                    _messages_to_claude_payload(active_body)
                    if claude_provider
                    else _messages_to_gemini_payload(active_body)
                    if native_gemini
                    else active_body
                )
                resp = await self._http.post(url, json=request_payload, headers=headers)
                resp.raise_for_status()
                sent_body = active_body
                if request_tools and "tools" in active_body:
                    self._tool_calls_supported = True
                break
            except httpx.HTTPStatusError as exc:
                body_text = _response_excerpt(exc.response)
                fallback_body: dict[str, Any] | None = None
                if not native_gemini and compat_retry_attempts < _GENERATION_COMPAT_MAX_RETRIES and exc.response.status_code in {400, 422}:
                    fallback_body = (
                        _structured_output_compat_retry_body(active_body, body_text)
                        or _generation_compat_retry_body(active_body, body_text)
                        or _multimodal_compat_retry_body(active_body, body_text)
                    )
                    if fallback_body is not None:
                        compat_retry_attempts += 1
                if (
                    fallback_body is None
                    and request_tools
                    and not tool_retry_used
                    and "tools" in active_body
                    and exc.response.status_code in {400, 422}
                ):
                    logger.warning(
                        "LLM tool-call request was rejected with HTTP %d, retrying without tools: %s",
                        exc.response.status_code,
                        redact_error_text(body_text, limit=500),
                    )
                    self._tool_calls_supported = False
                    fallback_body = dict(active_body)
                    fallback_body.pop("tools", None)
                    fallback_body.pop("tool_choice", None)
                    tool_retry_used = True
                if fallback_body is None:
                    _raise_llm_http_error(exc, context="LLM chat")
                active_body = fallback_body
        raw_data = resp.json()
        data = (
            _claude_response_to_chat_completion(raw_data)
            if claude_provider
            else _gemini_response_to_chat_completion(raw_data)
            if native_gemini
            else raw_data
        )

        if not claude_provider and _should_retry_empty_reasoning_response(data, effective_output_tokens):
            retry_body = dict(sent_body)
            retry_body["max_tokens"] = _EMPTY_REASONING_RETRY_MIN_TOKENS
            logger.info(
                "LLM returned only reasoning content with max_tokens=%s; retrying with max_tokens=%s",
                effective_output_tokens,
                _EMPTY_REASONING_RETRY_MIN_TOKENS,
            )
            try:
                retry_payload = _messages_to_gemini_payload(retry_body) if native_gemini else retry_body
                resp = await self._http.post(url, json=retry_payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as retry_exc:
                _raise_llm_http_error(retry_exc, context="LLM empty-reasoning retry chat")
            raw_data = resp.json()
            data = _gemini_response_to_chat_completion(raw_data) if native_gemini else raw_data

        choices = data.get("choices") or []
        if not choices:
            return {"reply": "", "tool_calls": [], "pet_control": None, "reasoning_content": ""}

        message = choices[0].get("message") or {}
        content = str(message.get("content") or "").strip()
        tool_calls = message.get("tool_calls") or []
        reasoning_content = str(message.get("reasoning_content") or message.get("reasoning") or "")
        final_reply, pet_control = extract_pet_control_payload(content)
        pet_control = filter_pet_control_payload(pet_control, pet_control_context)

        return {
            "reply": final_reply,
            "tool_calls": tool_calls,
            "pet_control": pet_control,
            "reasoning_content": reasoning_content,
            "raw": data,
        }

    async def rewrite_session_summary(
        self,
        mgr: GenerationManager,
        session_id: str,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Force a single LLM-based summary rewrite for a session."""
        if not self._http:
            mgr.record_summary_audit(session_id, source=source, outcome="error", detail="llm_not_initialized")
            return {"ok": False, "message": "LLM client not initialized"}

        source_text = mgr.build_summary_rewrite_source(session_id)
        if not source_text.strip():
            mgr.record_summary_audit(session_id, source=source, outcome="skipped", detail="no_source_text")
            return {"ok": False, "message": "No source text for summary rewrite"}

        headers = build_llm_auth_headers(self.api_key, self.provider)

        rewritten = await _rewrite_summary_with_llm(
            http_client=self._http,
            base_url=self.base_url,
            headers=headers,
            model=self.model,
            source_text=source_text,
            provider=self.provider,
        )
        if not rewritten:
            mgr.record_summary_audit(session_id, source=source, outcome="error", detail="empty_summary")
            return {"ok": False, "message": "Summary rewrite returned empty content"}

        mgr.apply_llm_summary(session_id, rewritten)

        scorer_mode = mgr.get_quality_scorer_mode()
        quality_detail = "quality=rule"
        if scorer_mode == "llm":
            allowed, reason = mgr.allow_llm_quality_scoring(session_id)
            if not allowed:
                quality_detail = f"quality=rule_skip({reason})"
            else:
                try:
                    scored = await _score_summary_with_llm(
                        http_client=self._http,
                        base_url=self.base_url,
                        headers=headers,
                        model=self.model,
                        summary_text=rewritten,
                        provider=self.provider,
                    )
                    if scored is not None:
                        mgr.update_quality_profile(
                            session_id,
                            scores=scored,
                            scorer="llm",
                            basis="llm-score-v1",
                        )
                        quality_detail = "quality=llm"
                    else:
                        quality_detail = "quality=rule_fallback(empty_llm_score)"
                except Exception as exc:
                    quality_detail = f"quality=rule_fallback({exc})"

        mgr.record_summary_audit(
            session_id,
            source=source,
            outcome="ok",
            detail=f"len={len(rewritten)}; {quality_detail}",
        )
        return {
            "ok": True,
            "message": "Summary rewritten",
            "summary": rewritten,
            "stats": mgr.get_summary_stats(session_id),
        }

    async def test_connection(self) -> dict[str, Any]:
        """Test upstream LLM connectivity."""
        if not self._http:
            return {"ok": False, "message": "LLM client not initialized"}

        headers = build_llm_auth_headers(self.api_key, self.provider)
        native_gemini = llm_protocol(self.provider, self.base_url) == "gemini-generate-content"

        try:
            # Try OpenAI-compatible models endpoint first, but still verify the
            # chat endpoint because some providers expose models while rejecting
            # the configured chat model or payload shape.
            resp = await self._http.get(llm_models_url(self.base_url, self.provider), headers=headers)
            resp.raise_for_status()
        except httpx.RequestError as exc:
            logger.warning("LLM models endpoint check failed: %s", exc)
        except httpx.HTTPStatusError as exc:
            body_text = _safe_response_excerpt(exc.response, limit=200)
            logger.warning("LLM models endpoint HTTP %d: %s", exc.response.status_code, body_text)

        try:
            # Minimal non-stream chat request against the actual configured model.
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "max_tokens": 1,
            }
            request_payload = (
                _messages_to_claude_payload(payload)
                if is_claude_provider(self.provider)
                else _messages_to_gemini_payload(payload)
                if native_gemini
                else payload
            )
            resp = await self._http.post(
                llm_request_url(self.base_url, self.provider, model=self.model),
                json=request_payload,
                headers=headers,
            )
            resp.raise_for_status()
            return {"ok": True, "message": "LLM connection OK (provider chat endpoint)"}
        except httpx.HTTPStatusError as exc:
            body_text = _safe_response_excerpt(exc.response, limit=200)
            return {
                "ok": False,
                "message": f"LLM API {exc.response.status_code}: {body_text}",
            }
        except httpx.RequestError as exc:
            return {"ok": False, "message": f"LLM request failed: {exc}"}

    async def list_models(self) -> list[str]:
        if not self._http:
            raise RuntimeError("LLM client not connected")
        resp = await self._http.get(llm_models_url(self.base_url, self.provider), headers=build_llm_auth_headers(self.api_key, self.provider))
        resp.raise_for_status()
        return extract_model_ids(resp.json())

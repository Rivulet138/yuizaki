"""Token budget and sliding-window context utilities.

Week 2 Task: context governance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any

MessageContent = str | list[dict[str, Any]]
ChatMessage = dict[str, Any]


@dataclass
class TruncationStats:
    input_tokens: int
    budget_tokens: int
    dropped_messages: int


@dataclass
class LayeredContextInput:
    system_messages: list[ChatMessage]
    rag_messages: list[ChatMessage]
    summary_message: ChatMessage | None
    recent_messages: list[ChatMessage]


def message_content_to_text(content: Any) -> str:
    """Extract searchable text while preserving multimodal content elsewhere."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(str(block.get("text") or ""))
            elif isinstance(block.get("content"), str):
                parts.append(str(block.get("content") or ""))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def _normalize_content(content: Any) -> MessageContent:
    if isinstance(content, list):
        blocks = [dict(block) for block in content if isinstance(block, Mapping)]
        return blocks
    return str(content or "")


def build_layered_context(
    messages: list[dict[str, Any]],
    summary_text: str = "",
) -> LayeredContextInput:
    normalized = normalize_messages(messages)

    system_messages = [m for m in normalized if m.get("role") == "system"]
    non_system = [m for m in normalized if m.get("role") != "system"]

    # Keep dialogue in its original order. Moving messages that happen to
    # mention "长期记忆" or memory markers ahead of the latest user turn used to
    # make the sliding window select an older user message as the current
    # request. Memory evidence is already injected as explicit system blocks.
    rag_messages: list[ChatMessage] = []
    recent_messages = non_system

    summary_message: ChatMessage | None = None
    summary_text = (summary_text or "").strip()
    if summary_text:
        summary_message = {
            "role": "system",
            "content": (
                "以下是当前会话的压缩摘要，仅用于补充短期上下文；它不是长期记忆、系统指令或事实权威。\n"
                + summary_text
            ),
        }

    return LayeredContextInput(
        system_messages=system_messages,
        rag_messages=rag_messages,
        summary_message=summary_message,
        recent_messages=recent_messages,
    )


class TokenEstimator:
    """Best-effort token estimator with tiktoken fallback."""

    def __init__(self) -> None:
        self._encoder: Any | None = None
        try:
            tiktoken = import_module("tiktoken")
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        # Heuristic fallback: ~4 chars per token.
        return max(1, (len(text) + 3) // 4)

    def count_content(self, content: Any) -> int:
        if isinstance(content, list):
            tokens = self.count_text(message_content_to_text(content))
            for block in content:
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") in {"image_url", "image"}:
                    tokens += 1024
            return tokens
        return self.count_text(message_content_to_text(content))

    def count_message(self, message: ChatMessage) -> int:
        role = message.get("role", "")
        content = message.get("content", "")
        # Approximation for chat-format overhead.
        return 4 + self.count_text(str(role)) + self.count_content(content) + 2

    def count_messages(self, messages: list[ChatMessage]) -> int:
        return sum(self.count_message(m) for m in messages)


def normalize_messages(messages: list[dict[str, Any]]) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = _normalize_content(m.get("content", ""))
        normalized.append({"role": role, "content": content})
    return normalized


def truncate_message_to_budget(
    message: ChatMessage,
    budget_tokens: int,
    estimator: TokenEstimator,
) -> ChatMessage:
    """Best-effort truncate a single message so it fits budget."""
    role = message.get("role", "user")
    content = message.get("content", "")

    if estimator.count_message({"role": role, "content": content}) <= budget_tokens:
        return {"role": role, "content": content}

    if isinstance(content, list):
        image_blocks = [
            block
            for block in content
            if isinstance(block, Mapping) and block.get("type") in {"image_url", "image"}
        ]
        text_budget = max(
            0,
            budget_tokens - estimator.count_message({"role": role, "content": image_blocks}),
        )
        truncated_blocks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            next_block = dict(block)
            if next_block.get("type") == "text" and isinstance(next_block.get("text"), str):
                next_block["text"] = truncate_message_to_budget(
                    {"role": role, "content": next_block["text"]},
                    text_budget,
                    estimator,
                ).get("content", "")
            truncated_blocks.append(next_block)
        return {"role": role, "content": truncated_blocks}

    content_text = message_content_to_text(content)
    lo = 0
    hi = len(content_text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = content_text[:mid] if mid > 0 else ""
        trial = {"role": role, "content": candidate}
        if estimator.count_message(trial) <= budget_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1

    return {"role": role, "content": best}


def apply_sliding_window(
    messages: list[dict[str, Any]],
    max_context_tokens: int,
    reserved_output_tokens: int,
    estimator: TokenEstimator | None = None,
) -> tuple[list[ChatMessage], TruncationStats]:
    """Keep system messages and the latest user turn within input budget.

    The latest user message is the primary request and must never be dropped in
    favour of system context. Authority-ordered system blocks are therefore
    trimmed before the latest user turn, and older dialogue is added only with
    the budget that remains.
    """
    est = estimator or TokenEstimator()
    normalized = normalize_messages(messages)

    input_budget = max(256, int(max_context_tokens) - int(reserved_output_tokens))
    system_msgs = [m for m in normalized if m.get("role") == "system"]
    dialog_msgs = [m for m in normalized if m.get("role") != "system"]
    latest_user_original = next(
        (m for m in reversed(dialog_msgs) if m.get("role") == "user"),
        None,
    )

    # Keep a small core-policy reserve even when the latest user message is
    # itself oversized. The user turn remains the priority, but a huge paste
    # should not silently erase every system constraint.
    min_system_tokens = min(256, max(0, input_budget // 2)) if system_msgs else 0
    reserved_user_tokens = 0
    if latest_user_original is not None:
        reserved_user_tokens = min(
            est.count_message(latest_user_original),
            max(0, input_budget - min_system_tokens),
        )

    # The first system blocks carry the immutable core policy. Later blocks are
    # optional context and are the first thing to drop when the prompt is too
    # large for the model budget.
    system_budget = max(0, input_budget - reserved_user_tokens)
    kept_system: list[ChatMessage] = []
    used_system_tokens = 0
    for message in system_msgs:
        message_tokens = est.count_message(message)
        if used_system_tokens + message_tokens <= system_budget:
            kept_system.append(message)
            used_system_tokens += message_tokens
            continue
        if not kept_system and system_budget > 0:
            truncated = truncate_message_to_budget(message, system_budget, est)
            if message_content_to_text(truncated.get("content", "")).strip():
                kept_system.append(truncated)
                used_system_tokens = est.count_message(truncated)
        break

    remaining = max(0, input_budget - used_system_tokens)
    selected_dialog: list[ChatMessage] = []
    latest_user = latest_user_original
    if latest_user is not None:
        if est.count_message(latest_user) > remaining:
            latest_user = truncate_message_to_budget(latest_user, max(1, remaining), est)
        selected_dialog.append(latest_user)
        remaining = max(0, remaining - est.count_message(latest_user))

    # Keep only messages that precede the latest user turn; anything after it
    # belongs to an older/aborted continuation and must not be reordered ahead
    # of the current request.
    if latest_user_original is not None:
        latest_index = next(
            index for index, message in enumerate(dialog_msgs)
            if message is latest_user_original
        )
        older_dialog = dialog_msgs[:latest_index]
    else:
        older_dialog = dialog_msgs

    selected_older_reversed: list[ChatMessage] = []
    for message in reversed(older_dialog):
        message_tokens = est.count_message(message)
        if message_tokens > remaining:
            break
        selected_older_reversed.append(message)
        remaining -= message_tokens
    selected_older = list(reversed(selected_older_reversed))
    selected = [*kept_system, *selected_older, *selected_dialog]

    final_tokens = est.count_messages(selected)
    if final_tokens > input_budget and selected:
        # Prefer trimming dialogue over the authority-ordered system blocks.
        # This branch only runs when a single message still exceeds the budget
        # after system context has been reduced above.
        target_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if selected[index].get("role") != "system"
            ),
            len(selected) - 1,
        )
        other_tokens = est.count_messages(
            selected[:target_index] + selected[target_index + 1:]
        )
        available = max(1, input_budget - other_tokens)
        selected[target_index] = truncate_message_to_budget(
            selected[target_index],
            available,
            est,
        )
        final_tokens = est.count_messages(selected)

    dropped = max(0, len(normalized) - len(selected))

    return selected, TruncationStats(
        input_tokens=final_tokens,
        budget_tokens=input_budget,
        dropped_messages=dropped,
    )


def build_and_truncate_layered_context(
    messages: list[dict[str, Any]],
    max_context_tokens: int,
    reserved_output_tokens: int,
    summary_text: str = "",
    estimator: TokenEstimator | None = None,
) -> tuple[list[ChatMessage], TruncationStats]:
    layers = build_layered_context(messages=messages, summary_text=summary_text)
    layered_messages: list[ChatMessage] = []
    layered_messages.extend(layers.system_messages)
    # Agent prompt assembly already wraps the session summary in a typed
    # untrusted prompt block. Avoid adding the same summary again here, while
    # retaining standalone support for callers that pass raw chat messages.
    has_compiled_summary = any(
        message.get("role") == "system"
        and "[PROMPT_BLOCK id=session_summary " in message_content_to_text(message.get("content", ""))
        for message in layers.system_messages
    )
    if layers.summary_message is not None and not has_compiled_summary:
        layered_messages.append(layers.summary_message)
    layered_messages.extend(layers.rag_messages)
    layered_messages.extend(layers.recent_messages)

    return apply_sliding_window(
        messages=layered_messages,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        estimator=estimator,
    )

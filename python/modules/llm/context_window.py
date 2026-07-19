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

    rag_messages: list[ChatMessage] = []
    recent_messages: list[ChatMessage] = []

    for m in non_system:
        content = message_content_to_text(m.get("content", ""))
        if m.get("role") == "system":
            continue
        if "长期记忆" in content or "[fact]" in content or "[preference]" in content or "[event]" in content:
            rag_messages.append(m)
        else:
            recent_messages.append(m)

    summary_message: ChatMessage | None = None
    summary_text = (summary_text or "").strip()
    if summary_text:
        summary_message = {
            "role": "system",
            "content": "以下是历史对话摘要（用于保持长期一致性）：\n" + summary_text,
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
    """Keep system messages + latest non-system turns within input budget."""
    est = estimator or TokenEstimator()
    normalized = normalize_messages(messages)

    input_budget = max(256, int(max_context_tokens) - int(reserved_output_tokens))
    system_msgs = [m for m in normalized if m.get("role") == "system"]
    dialog_msgs = [m for m in normalized if m.get("role") != "system"]

    selected_dialog: list[ChatMessage] = []
    running_tokens = est.count_messages(system_msgs)

    # Sliding window from the latest message backwards.
    for m in reversed(dialog_msgs):
        t = est.count_message(m)
        if running_tokens + t > input_budget and selected_dialog:
            break
        if running_tokens + t > input_budget and not selected_dialog:
            # Always keep at least the latest dialog message, even if the
            # current system prompt set pushes us temporarily over budget.
            # We will trim system prompts in the next step if needed.
            selected_dialog.append(m)
            running_tokens += t
            break
        if running_tokens + t <= input_budget:
            selected_dialog.append(m)
            running_tokens += t

    selected_dialog.reverse()
    selected = system_msgs + selected_dialog

    # Prompt assembly is authority ordered: the earliest system blocks contain
    # the immutable core policy, while later blocks are lower-authority context.
    if est.count_messages(selected) > input_budget and system_msgs:
        kept_system: list[ChatMessage] = []
        running = 0
        for m in system_msgs:
            t = est.count_message(m)
            if running + t > input_budget and kept_system:
                break
            if running + t <= input_budget or not kept_system:
                kept_system.append(m)
                running += t
        selected = kept_system

    final_tokens = est.count_messages(selected)

    if final_tokens > input_budget and selected:
        selected[-1] = truncate_message_to_budget(selected[-1], input_budget, est)
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
    if layers.summary_message is not None:
        layered_messages.append(layers.summary_message)
    layered_messages.extend(layers.rag_messages)
    layered_messages.extend(layers.recent_messages)

    return apply_sliding_window(
        messages=layered_messages,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        estimator=estimator,
    )

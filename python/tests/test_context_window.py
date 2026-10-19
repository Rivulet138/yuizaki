from __future__ import annotations

from modules.core.state import GenerationManager
from modules.llm.context_window import (
    apply_sliding_window,
    build_and_truncate_layered_context,
    message_content_to_text,
)


def test_compiled_session_summary_is_not_added_a_second_time() -> None:
    summary = "用户偏好本地模型"
    messages = [{
        "role": "system",
        "content": (
            "[PROMPT_BLOCK id=session_summary source=conversation_summary "
            "trust=untrusted authority=evidence order=510]\n"
            f"{summary}\n"
            "[END_PROMPT_BLOCK id=session_summary]"
        ),
    }, {"role": "user", "content": "继续"}]

    windowed, _ = build_and_truncate_layered_context(
        messages,
        max_context_tokens=4096,
        reserved_output_tokens=512,
        summary_text=summary,
    )

    rendered = "\n".join(message_content_to_text(item.get("content", "")) for item in windowed)
    assert rendered.count(summary) == 1


def test_stale_summary_rewrite_cannot_overwrite_new_history() -> None:
    manager = GenerationManager()
    manager.update_summary_policy(
        trigger_messages=1,
        keep_recent_messages=1,
        item_max_chars=140,
        rewrite_interval_messages=6,
    )
    manager.append_history("session", "user", "第一条")
    manager.append_history("session", "assistant", "第二条")

    _, source_revision = manager.get_summary_rewrite_snapshot("session")
    assert manager.apply_llm_summary("session", "旧重写", expected_revision=source_revision)
    manager.append_history("session", "user", "更新后的消息")

    assert not manager.apply_llm_summary("session", "过期重写", expected_revision=source_revision)
    assert manager.get_summary("session") != "过期重写"


def test_repeated_fallback_compression_keeps_previous_summary() -> None:
    manager = GenerationManager()
    manager.update_summary_policy(
        trigger_messages=1,
        keep_recent_messages=1,
        item_max_chars=140,
        rewrite_interval_messages=6,
    )

    manager.append_history("session", "user", "第一阶段目标")
    manager.append_history("session", "assistant", "第一阶段结论")
    first_summary = manager.get_summary("session")
    assert "第一阶段目标" in first_summary

    manager.append_history("session", "user", "第二阶段目标")
    manager.append_history("session", "assistant", "第二阶段结论")
    second_summary = manager.get_summary("session")

    assert "第一阶段目标" in second_summary
    assert "第二阶段目标" in second_summary
    assert "【新增对话】" in second_summary


def test_oversized_system_prompt_keeps_latest_user_message() -> None:
    messages = [
        {"role": "system", "content": "policy " * 5000},
        {"role": "user", "content": "hello"},
    ]

    windowed, stats = apply_sliding_window(
        messages,
        max_context_tokens=4096,
        reserved_output_tokens=1024,
    )

    assert any(
        message.get("role") == "user" and message.get("content") == "hello"
        for message in windowed
    )
    assert stats.dropped_messages == 0


def test_latest_user_message_wins_over_older_dialog() -> None:
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "old question " * 600},
        {"role": "assistant", "content": "old answer " * 600},
        {"role": "user", "content": "current question"},
    ]

    windowed, _ = apply_sliding_window(
        messages,
        max_context_tokens=2048,
        reserved_output_tokens=512,
    )

    roles = [message.get("role") for message in windowed]
    assert roles[0] == "system"
    assert windowed[-1] == {"role": "user", "content": "current question"}
    assert all(
        message.get("content") != "old question " * 600
        for message in windowed
    )


def test_memory_mention_does_not_move_current_user_before_history() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "opening"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "长期记忆里有什么？"},
    ]

    windowed, _ = build_and_truncate_layered_context(messages, max_context_tokens=8192, reserved_output_tokens=1024)

    assert [message["role"] for message in windowed] == [
        "system", "assistant", "user", "assistant", "user",
    ]
    assert windowed[-1]["content"] == "长期记忆里有什么？"
    assert windowed[2]["content"] == "first question"
    assert windowed[3]["content"] == "first answer"


def test_large_latest_user_message_is_truncated_but_retained() -> None:
    large_user = "x" * 20000
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": large_user},
    ]

    windowed, _ = apply_sliding_window(
        messages,
        max_context_tokens=1024,
        reserved_output_tokens=256,
    )

    user_messages = [message for message in windowed if message.get("role") == "user"]
    assert len(user_messages) == 1
    assert 0 < len(str(user_messages[0].get("content"))) < len(large_user)
    assert any(message.get("role") == "system" for message in windowed)


def test_normal_window_preserves_chronological_order() -> None:
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]

    windowed, _ = apply_sliding_window(
        messages,
        max_context_tokens=8192,
        reserved_output_tokens=1024,
    )

    assert windowed == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]

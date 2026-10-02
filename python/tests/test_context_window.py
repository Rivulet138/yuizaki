from __future__ import annotations

from modules.core.state import GenerationManager
from modules.llm.context_window import build_and_truncate_layered_context, message_content_to_text


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

from __future__ import annotations

from types import SimpleNamespace

from modules.system.memory_write_pipeline import (
    build_user_signal_event,
    classify_user_signal_kind,
    extract_auto_fact,
    extract_explicit_memory_fact,
    normalize_relationship_memory_payload,
)
from modules.system.relationship_policy import (
    normalize_relationship_importance,
    resolve_relationship_scope,
)
from modules.system.relationship_runtime import collect_relationship_events


def test_explicit_remember_is_extracted_as_a_user_fact_candidate() -> None:
    event = build_user_signal_event(
        "记住：我对花生过敏",
        workspace_id="default",
        turn_id="turn-1",
    )

    assert event is not None
    assert event["kind"] == "explicit_memory"
    assert event["type"] == "fact"
    assert event["layer"] == "profile"
    assert "花生" in event["text"]
    assert event["metadata"]["memory_role"] == "user_fact"
    assert event["metadata"]["review_status"] == "pending"
    assert event["metadata"]["review_required"] is True

    normalized = normalize_relationship_memory_payload(
        event,
        active_workspace_id="default",
        companion_id="default",
        resolve_relationship_scope=resolve_relationship_scope,
        normalize_relationship_importance=normalize_relationship_importance,
    )
    assert normalized["layer"] == "profile"
    assert normalized["metadata"]["review_status"] == "pending"
    assert normalized["metadata"]["memory_role"] == "user_fact"
    assert normalized["metadata"]["event_type"] == "explicit_memory"
    assert normalized["metadata"]["relationship_event"] == {}


def test_explicit_remember_does_not_match_incidental_mentions() -> None:
    assert extract_explicit_memory_fact("我不记得这件事") is None
    assert classify_user_signal_kind("我不记得这件事") == (None, None)
    assert extract_explicit_memory_fact("请记住：明天下午三点开会") == "明天下午三点开会"


def test_explicit_remember_supports_english_prefix() -> None:
    assert extract_explicit_memory_fact("Remember that I prefer tea") == "I prefer tea"


def test_explicit_memory_keeps_only_the_first_sentence() -> None:
    assert extract_explicit_memory_fact("记住：我对花生过敏。别的以后再说") == "我对花生过敏"


def test_explicit_memory_ignores_reminder_requests() -> None:
    for text in (
        "记住要带伞",
        "请记住要交报告",
        "Remember to call mom tomorrow",
        "remember that you should reply in Chinese",
    ):
        assert extract_explicit_memory_fact(text) is None, text
        assert classify_user_signal_kind(text)[0] != "explicit_memory", text


def test_explicit_memory_is_not_collected_as_relationship_history() -> None:
    timestamp = "2026-01-01T00:00:00+00:00"
    document = SimpleNamespace(
        text="用户明确要求记住：对花生过敏",
        metadata={
            "event_type": "explicit_memory",
            "scope": "profile",
            "companion_id": "default",
            "workspace_id": "default",
            "review_status": "approved",
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    store = SimpleNamespace(list_documents=lambda: [document])

    events = collect_relationship_events(
        memory_store=store,
        companion_id="default",
        limit=10,
    )

    assert events == []


def test_existing_preference_detection_is_unchanged() -> None:
    assert classify_user_signal_kind("我喜欢喝美式咖啡")[0] == "preference_confirmed"
    assert classify_user_signal_kind("谢谢你的帮助")[0] == "gratitude"


def test_auto_fact_captures_high_precision_self_disclosure() -> None:
    event = build_user_signal_event(
        "顺便说一下，我住在东京。",
        workspace_id="default",
        turn_id="turn-2",
    )

    assert event is not None
    assert event["kind"] == "auto_fact"
    assert event["type"] == "fact"
    assert event["layer"] == "profile"
    assert event["text"] == "用户陈述的自身事实：我住在东京"
    assert event["metadata"]["memory_role"] == "user_fact"
    assert event["metadata"]["review_status"] == "pending"


def test_auto_fact_ignores_questions_and_third_party_statements() -> None:
    for text in (
        "你住在哪里？",
        "你养了猫吗？",
        "他说他住在东京",
        "Do you live in Tokyo?",
        "随便聊聊吧",
        "我在考虑要不要辞掉工作",
        "我叫什么来着",
        "我是不是该换个工作",
        "我想我住在东京",
    ):
        assert extract_auto_fact(text) is None, text


def test_auto_fact_supports_common_english_statements() -> None:
    assert extract_auto_fact("I live in Osaka with my family") == "I live in Osaka with my family"
    assert extract_auto_fact("My birthday is in May") == "My birthday is in May"


def test_tool_success_evidence_redacts_secret_arguments() -> None:
    from modules.system.memory_write_pipeline import build_tool_success_event

    event = build_tool_success_event(
        tool_name="demo.write",
        args={"api_key": "sk-secret", "path": "C:/private/file.txt", "nested": {"token": "tok"}},
        text="done",
        importance=0.8,
        owner_agent_id="agent",
        owner_agent_role="worker",
    )

    evidence = event["metadata"]["evidence"]
    assert evidence["api_key"] == "[redacted]"
    assert evidence["nested"]["token"] == "[redacted]"
    assert "sk-secret" not in repr(event)
    assert "C:/private/file.txt" in repr(event)

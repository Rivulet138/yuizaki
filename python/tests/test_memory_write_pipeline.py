from __future__ import annotations

from types import SimpleNamespace

from modules.system.memory_write_pipeline import (
    build_user_signal_event,
    classify_user_signal_kind,
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

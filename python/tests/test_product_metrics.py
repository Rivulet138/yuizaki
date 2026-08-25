from __future__ import annotations

import pytest

from evals.product_metrics import (
    ConsentGatedProductEventExporter,
    JsonlProductEventStore,
    JsonProductConsentStateStore,
    JsonProductExportJournal,
    compute_product_metrics,
    normalize_product_event,
)


def test_product_metrics_use_explicit_denominators_and_d7_cohort() -> None:
    events = [
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "conversation", "success": True},
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "voice", "action": "turn"},
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "memory", "action": "write"},
        {"user_id": "u1", "timestamp": "2026-08-02", "kind": "memory", "action": "correction"},
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "proactive", "action": "prompt"},
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "proactive", "action": "accepted"},
        {"user_id": "u1", "timestamp": "2026-08-08", "kind": "conversation", "success": True},
        {"user_id": "u1", "timestamp": "2026-08-01", "kind": "recovery", "action": "attempt", "success": True},
        {"user_id": "u2", "timestamp": "2026-08-01", "kind": "conversation", "success": False},
        {"user_id": "u2", "timestamp": "not-a-date", "kind": "conversation", "success": True},
    ]

    report = compute_product_metrics(events)

    assert report["event_count"] == 9
    assert report["dropped_event_count"] == 1
    assert report["first_successful_conversation_rate"] == 0.5
    assert report["d7_retention_rate"] == 0.5
    assert report["voice_adoption_rate"] == 0.5
    assert report["memory_correction_rate"] == 1.0
    assert report["proactive_acceptance_rate"] == 1.0
    assert report["recovery_success_rate"] == 1.0


def test_product_metrics_return_none_for_empty_denominators() -> None:
    report = compute_product_metrics([])

    assert report["active_user_count"] == 0
    assert report["d7_retention_rate"] is None
    assert report["voice_adoption_rate"] is None
    assert report["memory_correction_rate"] is None
    assert report["proactive_acceptance_rate"] is None
    assert report["recovery_success_rate"] is None
    with pytest.raises(ValueError, match="retention_days"):
        compute_product_metrics([], retention_days=0)


def test_product_metrics_exclude_immature_users_from_d7_denominator() -> None:
    report = compute_product_metrics([
        {"user_id": "mature", "timestamp": "2026-08-01", "kind": "conversation", "success": True},
        {"user_id": "mature", "timestamp": "2026-08-08", "kind": "conversation", "success": True},
        {"user_id": "immature", "timestamp": "2026-08-07", "kind": "conversation", "success": True},
        {"user_id": "future", "timestamp": "2026-08-10", "kind": "conversation", "success": True},
    ], observation_end_date="2026-08-08")

    assert report["active_user_count"] == 2
    assert report["outside_observation_event_count"] == 1
    assert report["d7_retention_rate"] == 1.0
    assert report["d7_retention"] == {
        "retained_users": 1,
        "cohort_users": 1,
        "excluded_immature_users": 1,
        "observation_end_date": "2026-08-08",
    }
    with pytest.raises(ValueError, match="observation_end_date"):
        compute_product_metrics([], observation_end_date="not-a-date")


def test_product_event_normalization_drops_content_and_unknown_actions() -> None:
    normalized = normalize_product_event({
        "user_id": "pseudonymous-user",
        "timestamp": "2026-08-01T12:30:00Z",
        "kind": "conversation",
        "success": True,
        "prompt": "private transcript must not be retained",
        "api_key": "secret",
    })

    assert normalized == {
        "user_id": "pseudonymous-user",
        "timestamp": "2026-08-01",
        "kind": "conversation",
        "success": True,
    }
    assert normalize_product_event({
        "user_id": "u1",
        "timestamp": "2026-08-01",
        "kind": "voice",
        "action": "raw_audio",
    }) is None


def test_product_event_normalization_rejects_direct_user_identifiers() -> None:
    base = {"timestamp": "2026-08-01", "kind": "conversation", "success": True}

    assert normalize_product_event({**base, "user_id": "person@example.com"}) is None
    assert normalize_product_event({**base, "user_id": "display name"}) is None
    assert normalize_product_event({**base, "user_id": "anon-device-01:42"}) == {
        "user_id": "anon-device-01:42",
        "timestamp": "2026-08-01",
        "kind": "conversation",
        "success": True,
    }


def test_jsonl_product_event_store_requires_consent_and_persists_normalized_events(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    event = {
        "user_id": "anon-1",
        "timestamp": "2026-08-23T10:00:00Z",
        "kind": "conversation",
        "success": True,
        "transcript": "must not be persisted",
        "prompt": "must not be persisted",
        "token": "secret",
    }
    disabled = JsonlProductEventStore(path)
    assert disabled.append(event) is False
    assert not path.exists()

    enabled = JsonlProductEventStore(path, consented=True)
    assert enabled.append(event) is True
    restored = JsonlProductEventStore(path, consented=True)
    assert restored.read() == [{
        "user_id": "anon-1",
        "timestamp": "2026-08-23",
        "kind": "conversation",
        "success": True,
    }]
    assert "transcript" not in path.read_text(encoding="utf-8")
    assert restored.metrics()["first_successful_conversation_rate"] == 1.0


def test_jsonl_product_event_store_rejects_corrupt_records(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"kind":"conversation"}\n', encoding="utf-8")
    store = JsonlProductEventStore(path, consented=True)
    with pytest.raises(ValueError, match="corrupt"):
        store.read()


def test_jsonl_product_event_store_purges_old_records_atomically(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path, consented=True)
    assert store.append({"user_id": "u1", "timestamp": "2026-08-01", "kind": "conversation", "success": True})
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})

    assert store.purge_before("2026-08-23") == 1
    assert [event["timestamp"] for event in store.read()] == ["2026-08-23"]
    assert not list(tmp_path.glob(".events.jsonl.tmp-*"))


def test_jsonl_product_event_store_revokes_consent_and_deletes_local_events(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path, consented=True)
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})

    store.revoke_consent()

    assert store.consented is False
    assert not path.exists()
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True}) is False


def test_jsonl_product_event_store_requires_explicit_consent_transition(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path)
    assert store.consented is False
    with pytest.raises(AttributeError):
        store.consented = True

    store.grant_consent()
    assert store.consented is True
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})


def test_jsonl_product_event_store_suppresses_small_cohorts_and_requires_consent(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path, consented=True)
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})

    suppressed = store.cohort_report(min_cohort_users=2)
    assert suppressed == {
        "status": "suppressed",
        "reason": "minimum_cohort_size",
        "min_cohort_users": 2,
        "window": {"start_date": None, "end_date": None},
        "metrics": None,
    }
    assert JsonlProductEventStore(path).cohort_report() == {
        "status": "disabled",
        "window": {"start_date": None, "end_date": None},
        "metrics": None,
    }

    assert store.append({"user_id": "u2", "timestamp": "2026-08-23", "kind": "conversation", "success": True})
    ready = store.cohort_report(min_cohort_users=2)
    assert ready["status"] == "ready"
    assert ready["metrics"]["active_user_count"] == 2


def test_jsonl_product_event_store_cohort_report_filters_an_explicit_window(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path, consented=True)
    assert store.append({"user_id": "u1", "timestamp": "2026-08-01", "kind": "conversation", "success": True})
    assert store.append({"user_id": "u2", "timestamp": "2026-08-23", "kind": "conversation", "success": True})

    report = store.cohort_report(
        min_cohort_users=1,
        start_date="2026-08-20",
        end_date="2026-08-31",
    )

    assert report["status"] == "ready"
    assert report["window"] == {"start_date": "2026-08-20", "end_date": "2026-08-31"}
    assert report["metrics"]["active_user_count"] == 1
    with pytest.raises(ValueError, match="end_date"):
        store.cohort_report(start_date="2026-08-31", end_date="2026-08-20")


def test_consent_gated_exporter_does_not_call_transport_without_consent(tmp_path) -> None:
    class Transport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, events) -> None:
            self.calls += 1

    transport = Transport()
    store = JsonlProductEventStore(tmp_path / "events.jsonl")
    exporter = ConsentGatedProductEventExporter(store, transport)

    assert exporter.export().status == "disabled"
    assert transport.calls == 0


def test_consent_gated_exporter_sends_only_normalized_events_after_consent(tmp_path) -> None:
    class Transport:
        def __init__(self) -> None:
            self.events = []

        def send(self, events) -> None:
            self.events.extend(events)

    transport = Transport()
    store = JsonlProductEventStore(tmp_path / "events.jsonl")
    store.grant_consent()
    assert store.append({
        "user_id": "anon-1",
        "timestamp": "2026-08-23T10:00:00Z",
        "kind": "conversation",
        "success": True,
        "prompt": "must not leave the local normalizer",
    })
    exporter = ConsentGatedProductEventExporter(store, transport)

    result = exporter.export()

    assert result.status == "sent"
    assert result.event_count == 1
    assert transport.events == [{
        "user_id": "anon-1",
        "timestamp": "2026-08-23",
        "kind": "conversation",
        "success": True,
    }]


def test_consent_gated_exporter_keeps_local_events_when_transport_fails(tmp_path) -> None:
    class FailingTransport:
        def send(self, events) -> None:
            raise RuntimeError("endpoint unavailable")

    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path)
    store.grant_consent()
    assert store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})

    result = ConsentGatedProductEventExporter(store, FailingTransport()).export()

    assert result.status == "failed"
    assert result.event_count == 0
    assert result.error_code == "transport_unavailable"
    assert result.idempotency_key is not None
    assert len(store.read()) == 1


def test_consent_gated_exporter_reuses_deterministic_batch_id_for_idempotent_transport(tmp_path) -> None:
    class BatchTransport:
        def __init__(self):
            self.calls = []

        def send_batch(self, events, *, idempotency_key):
            self.calls.append((tuple(events), idempotency_key))

    store = JsonlProductEventStore(tmp_path / "events.jsonl")
    store.grant_consent()
    store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})
    transport = BatchTransport()
    exporter = ConsentGatedProductEventExporter(store, transport)

    first = exporter.export()
    second = exporter.export()
    assert first.status == "sent"
    assert first.idempotency_key
    assert second.idempotency_key == first.idempotency_key
    assert len(transport.calls) == 2
    assert transport.calls[0][1] == transport.calls[1][1] == first.idempotency_key


def test_exporter_revokes_local_consent_before_optional_remote_delete(tmp_path) -> None:
    class DeletingTransport:
        def __init__(self):
            self.keys = []

        def delete_batch(self, *, idempotency_key):
            self.keys.append(idempotency_key)

    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path)
    store.grant_consent()
    store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})
    transport = DeletingTransport()
    result = ConsentGatedProductEventExporter(store, transport).revoke_consent()

    assert result.local_status == "revoked"
    assert result.remote_status == "deleted"
    assert result.idempotency_key == transport.keys[0]
    assert not path.exists()


def test_exporter_keeps_local_revoke_when_remote_delete_fails(tmp_path) -> None:
    class FailingDeleteTransport:
        def delete_batch(self, *, idempotency_key):
            raise RuntimeError("remote unavailable")

    path = tmp_path / "events.jsonl"
    store = JsonlProductEventStore(path)
    store.grant_consent()
    store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})
    result = ConsentGatedProductEventExporter(store, FailingDeleteTransport()).revoke_consent()

    assert result.local_status == "revoked"
    assert result.remote_status == "failed"
    assert result.error_code == "remote_delete_failed"
    assert not path.exists()


def test_consent_state_survives_restart_and_revoke_is_durable(tmp_path) -> None:
    event_path = tmp_path / "events.jsonl"
    consent_path = tmp_path / "consent.json"
    consent_store = JsonProductConsentStateStore(consent_path)
    first = JsonlProductEventStore(event_path, consented=True, consent_state_store=consent_store)
    assert first.consented is False
    first.grant_consent()
    assert first.consented is True
    assert consent_store.load() is True

    restarted = JsonlProductEventStore(event_path, consent_state_store=consent_store)
    assert restarted.consented is True
    restarted.revoke_consent()

    assert restarted.consented is False
    assert JsonProductConsentStateStore(consent_path).load() is False
    assert not event_path.exists()


def test_corrupt_consent_state_fails_closed(tmp_path) -> None:
    consent_path = tmp_path / "consent.json"
    consent_path.write_text('{"schema_version":1,"consented":"yes"}', encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt"):
        JsonProductConsentStateStore(consent_path).load()


def test_export_journal_persists_only_redacted_batch_state_and_recovers_deletion(tmp_path) -> None:
    journal_path = tmp_path / "export-journal.json"
    journal = JsonProductExportJournal(journal_path)
    key = "a" * 64

    journal.record_export_attempt(key, 2)
    journal.record_export_failed(key, "transport_unavailable")
    assert journal.read()[key].status == "export_pending"
    assert journal.read()[key].attempts == 1
    journal_text = journal_path.read_text(encoding="utf-8")
    assert "transcript" not in journal_text
    assert "transport_unavailable" in journal_text

    journal.record_deletion_pending(key, 2)
    assert journal.pending_deletions() == [(key, 2)]
    restarted = JsonProductExportJournal(journal_path)
    restarted.record_deleted(key)
    assert restarted.pending_deletions() == []


def test_export_journal_rejects_corrupt_or_unbounded_state(tmp_path) -> None:
    path = tmp_path / "export-journal.json"
    path.write_text('{"schema_version":1,"entries":{"bad":{"event_count":0,"status":"deleted","attempts":0,"last_error":null}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        JsonProductExportJournal(path).read()

    bounded = JsonProductExportJournal(tmp_path / "bounded.json", max_entries=1)
    bounded.record_export_attempt("b" * 64, 1)
    with pytest.raises(ValueError, match="capacity"):
        bounded.record_export_attempt("c" * 64, 1)
    with pytest.raises(ValueError, match="error code"):
        bounded.record_export_failed("b" * 64, "contains secret")


def test_exporter_retries_pending_remote_deletion_after_restart(tmp_path) -> None:
    class Transport:
        def __init__(self) -> None:
            self.delete_keys = []

        def delete_batch(self, *, idempotency_key):
            self.delete_keys.append(idempotency_key)

    event_path = tmp_path / "events.jsonl"
    journal_path = tmp_path / "export-journal.json"
    store = JsonlProductEventStore(event_path)
    store.grant_consent()
    store.append({"user_id": "u1", "timestamp": "2026-08-23", "kind": "conversation", "success": True})
    transport = Transport()
    journal = JsonProductExportJournal(journal_path)
    exporter = ConsentGatedProductEventExporter(store, transport, journal=journal)

    transport.delete_batch = lambda **_: (_ for _ in ()).throw(RuntimeError("offline"))
    failed = exporter.revoke_consent()
    assert failed.remote_status == "failed"
    pending_key = failed.idempotency_key
    assert pending_key is not None
    assert JsonProductExportJournal(journal_path).pending_deletions() == [(pending_key, 1)]

    retry_transport = Transport()
    retried = ConsentGatedProductEventExporter(
        JsonlProductEventStore(event_path), retry_transport, journal=JsonProductExportJournal(journal_path)
    ).retry_pending_deletions()
    assert retried == type(retried)(attempted=1, deleted=1, failed=0)
    assert retry_transport.delete_keys == [pending_key]
    assert JsonProductExportJournal(journal_path).pending_deletions() == []

from __future__ import annotations

import httpx
import pytest

from evals.product_metrics_transport import (
    HttpProductEventTransport,
    parse_product_batch_receipt,
    parse_product_deletion_receipt,
)


def _transport(handler, **kwargs):
    return HttpProductEventTransport(
        "https://metrics.example.test/v1/events",
        allowed_origins=["https://metrics.example.test"],
        bearer_token="secret-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        **kwargs,
    )


def test_transport_sends_auth_and_idempotency_without_leaking_token() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    transport = _transport(handler)
    transport.send_batch([{"kind": "conversation"}], idempotency_key="a" * 64)

    assert requests[0].headers["Authorization"] == "Bearer secret-token"
    assert requests[0].headers["Idempotency-Key"] == "a" * 64
    assert "secret-token" not in str(requests[0].url)
    transport.close()


def test_transport_retries_transient_http_failures_and_accepts_duplicate() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts < 3 else 409)

    transport = _transport(handler, max_attempts=3)
    transport.send_batch([], idempotency_key="b" * 64)
    assert attempts == 3
    transport.close()


def test_transport_can_require_an_exact_server_batch_receipt() -> None:
    key = "1" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(202, json={
            "schema_version": 1,
            "idempotency_key": key,
            "event_count": 2,
            "status": "accepted",
        })

    transport = _transport(handler, require_batch_receipt=True)
    transport.send_batch([{"kind": "conversation"}, {"kind": "voice"}], idempotency_key=key)
    transport.close()


def test_transport_rejects_missing_or_mismatched_batch_receipts() -> None:
    key = "2" * 64
    missing = _transport(lambda _request: httpx.Response(202), require_batch_receipt=True)
    with pytest.raises(ValueError, match="receipt"):
        missing.send_batch([], idempotency_key=key)
    missing.close()

    with pytest.raises(ValueError, match="receipt"):
        parse_product_batch_receipt({
            "schema_version": 1,
            "idempotency_key": key,
            "event_count": 2,
            "status": "accepted",
        }, expected_key=key, expected_event_count=1)


def test_transport_rejects_insecure_or_unallowlisted_endpoints() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HttpProductEventTransport("http://metrics.example.test/events", allowed_origins=["http://metrics.example.test"], bearer_token="token")
    with pytest.raises(ValueError, match="allowlisted"):
        HttpProductEventTransport("https://other.example.test/events", allowed_origins=["https://metrics.example.test"], bearer_token="token")


def test_transport_bounds_payload_and_requires_deletion_endpoint(tmp_path) -> None:
    transport = _transport(lambda request: httpx.Response(204), max_payload_bytes=20)
    with pytest.raises(ValueError, match="payload"):
        transport.send_batch([{"large": "x" * 100}], idempotency_key="c" * 64)
    with pytest.raises(RuntimeError, match="deletion endpoint"):
        transport.delete_batch(idempotency_key="c" * 64)
    transport.close()


def test_transport_supports_authenticated_deletion_ack() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    transport = _transport(handler, delete_endpoint="https://metrics.example.test/v1/events")
    transport.delete_batch(idempotency_key="d" * 64)
    assert requests[0].method == "DELETE"
    assert requests[0].headers["Idempotency-Key"] == "d" * 64
    transport.close()


def test_transport_can_require_a_strict_server_deletion_receipt() -> None:
    key = "e" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={
            "schema_version": 1,
            "idempotency_key": key,
            "status": "deleted",
        })

    transport = _transport(handler, delete_endpoint="https://metrics.example.test/v1/events", require_deletion_receipt=True)
    transport.delete_batch(idempotency_key=key)
    transport.close()


def test_transport_rejects_missing_or_mismatched_deletion_receipts() -> None:
    key = "f" * 64

    def missing_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    missing = _transport(
        missing_handler,
        delete_endpoint="https://metrics.example.test/v1/events",
        require_deletion_receipt=True,
    )
    with pytest.raises(ValueError, match="receipt"):
        missing.delete_batch(idempotency_key=key)
    missing.close()

    with pytest.raises(ValueError, match="receipt"):
        parse_product_deletion_receipt({
            "schema_version": 1,
            "idempotency_key": "0" * 64,
            "status": "deleted",
        }, expected_key=key)

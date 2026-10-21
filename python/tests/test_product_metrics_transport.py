from __future__ import annotations

import httpx
import pytest

from evals.product_metrics_transport import HttpProductEventTransport


KEY = "a" * 64


def _client(response: httpx.Response) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: response))


def test_batch_receipt_is_required_by_default() -> None:
    transport = HttpProductEventTransport(
        "https://metrics.example.test/v1/events",
        allowed_origins=["https://metrics.example.test"],
        bearer_token="runtime-token",
        client=_client(httpx.Response(202, json={"accepted": True})),
    )

    with pytest.raises(ValueError, match="batch receipt is invalid"):
        transport.send_batch([{"event": "turn.completed"}], idempotency_key=KEY)


def test_valid_batch_receipt_is_accepted_by_default() -> None:
    transport = HttpProductEventTransport(
        "https://metrics.example.test/v1/events",
        allowed_origins=["https://metrics.example.test"],
        bearer_token="runtime-token",
        client=_client(
            httpx.Response(
                202,
                json={
                    "schema_version": 1,
                    "idempotency_key": KEY,
                    "event_count": 1,
                    "status": "accepted",
                },
            ),
        ),
    )

    transport.send_batch([{"event": "turn.completed"}], idempotency_key=KEY)


def test_deletion_receipt_is_required_by_default() -> None:
    transport = HttpProductEventTransport(
        "https://metrics.example.test/v1/events",
        allowed_origins=["https://metrics.example.test"],
        bearer_token="runtime-token",
        delete_endpoint="https://metrics.example.test/v1/events",
        client=_client(httpx.Response(204)),
    )

    with pytest.raises(ValueError, match="deletion receipt is missing"):
        transport.delete_batch(idempotency_key=KEY)

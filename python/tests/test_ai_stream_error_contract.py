from __future__ import annotations

import asyncio

from modules.agent.turn_service import TurnClaimLostError, TurnIdentityConflictError
from routes.ai_api import _stream_error_contract


def test_stream_error_contract_marks_identity_conflicts_non_retryable() -> None:
    payload = _stream_error_contract(
        TurnIdentityConflictError("different semantic input"),
        request_id="request-1",
        turn_id="turn-1",
    )

    assert payload["code"] == "turn_identity_conflict"
    assert payload["retryable"] is False
    assert payload["request_id"] == "request-1"
    assert payload["turn_id"] == "turn-1"


def test_stream_error_contract_distinguishes_timeout_and_claim_loss() -> None:
    timeout = _stream_error_contract(
        asyncio.TimeoutError(), request_id="request-1", turn_id="turn-1"
    )
    claim_lost = _stream_error_contract(
        TurnClaimLostError("claim expired"), request_id="request-1", turn_id="turn-1"
    )

    assert timeout["code"] == "upstream_timeout"
    assert timeout["retryable"] is True
    assert claim_lost["code"] == "turn_claim_lost"
    assert claim_lost["retryable"] is False

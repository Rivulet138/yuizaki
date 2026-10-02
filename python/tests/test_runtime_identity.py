from __future__ import annotations

import hashlib
import hmac

import pytest

import app


@pytest.mark.asyncio
async def test_ping_returns_authenticated_runtime_proof_for_valid_challenge(monkeypatch) -> None:
    token = "backend-test-token"
    challenge = "ab" * 32
    monkeypatch.setattr(app, "_BACKEND_API_TOKEN", token)
    for key, value in {
        "YUIZAKI_RUNTIME_SERVICE": "yuizaki-python-backend",
        "YUIZAKI_RUNTIME_SERVICE_VERSION": "test",
        "YUIZAKI_RUNTIME_INSTANCE_ID": "instance-1",
        "YUIZAKI_RUNTIME_GENERATION": "3",
        "YUIZAKI_RUNTIME_STARTUP_NONCE": "nonce-1",
    }.items():
        monkeypatch.setenv(key, value)

    payload = await app.ping(challenge)

    assert payload["runtime"]["instance_id"] == "instance-1"
    assert payload["runtime_proof"] == hmac.new(
        token.encode(),
        f"yuizaki-backend-proof-v1:{challenge}".encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.asyncio
async def test_ping_does_not_emit_proof_for_invalid_challenge_or_missing_token(monkeypatch) -> None:
    monkeypatch.setattr(app, "_BACKEND_API_TOKEN", "backend-test-token")

    invalid = await app.ping("not-hex")
    assert "runtime_proof" not in invalid

    monkeypatch.setattr(app, "_BACKEND_API_TOKEN", "")
    missing_token = await app.ping("ab" * 32)
    assert "runtime_proof" not in missing_token

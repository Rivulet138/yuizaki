"""Transport-neutral StagePort contract for optional browser/mobile/IM clients.

Stage adapters carry the shared companion event contract; they never own Agent
planning. Encryption is deliberately injected so deployments use a reviewed
AEAD implementation instead of a home-grown cipher.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class StageSession:
    stage_id: str
    workspace_id: str
    session_id: str
    subject_id: str
    scopes: frozenset[str] = frozenset()
    expires_at: float = 0.0

    def validate(self, *, workspace_id: str, session_id: str, now: float | None = None) -> None:
        if self.workspace_id != workspace_id or self.session_id != session_id:
            raise PermissionError("stage_session_scope_mismatch")
        if self.expires_at and (now if now is not None else time.time()) >= self.expires_at:
            raise PermissionError("stage_session_expired")


@dataclass(frozen=True)
class StageEvent:
    schema_version: int
    event_id: str
    workspace_id: str
    session_id: str
    turn_id: str
    generation_id: str | None
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def validate(self, session: StageSession) -> None:
        session.validate(workspace_id=self.workspace_id, session_id=self.session_id)
        if self.schema_version != 1:
            raise ValueError("unsupported_stage_event_schema")
        if not self.event_id or not self.turn_id or self.sequence < 0:
            raise ValueError("invalid_stage_event_identity")


@runtime_checkable
class StagePort(Protocol):
    async def send(self, session: StageSession, event: StageEvent) -> None: ...

    async def cancel(self, session: StageSession, *, turn_id: str, reason: str) -> None: ...

    async def request_turn(
        self,
        session: StageSession,
        *,
        messages: list[dict[str, Any]],
        idempotency_key: str,
        permission_scope: str,
    ) -> Mapping[str, Any]: ...


class SyncEncryptionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptedSyncEnvelope:
    key_id: str
    algorithm: str
    ciphertext: bytes
    associated_data: bytes
    digest: str


@runtime_checkable
class SyncCipher(Protocol):
    algorithm: str

    def encrypt(self, plaintext: bytes, associated_data: bytes) -> tuple[str, bytes]: ...

    def decrypt(self, ciphertext: bytes, associated_data: bytes, key_id: str) -> bytes: ...


class EncryptedSyncCodec:
    """Encode/decode optional sync payloads with an injected AEAD cipher."""

    def __init__(self, cipher: SyncCipher | None = None) -> None:
        self.cipher = cipher

    def encode(self, payload: bytes, *, associated_data: bytes = b"") -> EncryptedSyncEnvelope:
        if self.cipher is None:
            raise SyncEncryptionUnavailable("encrypted_sync_requires_aead_provider")
        key_id, ciphertext = self.cipher.encrypt(payload, associated_data)
        digest = hashlib.sha256(payload).hexdigest()
        return EncryptedSyncEnvelope(
            key_id=key_id,
            algorithm=str(self.cipher.algorithm),
            ciphertext=ciphertext,
            associated_data=associated_data,
            digest=digest,
        )

    def decode(self, envelope: EncryptedSyncEnvelope) -> bytes:
        if self.cipher is None:
            raise SyncEncryptionUnavailable("encrypted_sync_requires_aead_provider")
        if envelope.algorithm != str(self.cipher.algorithm):
            raise ValueError("sync_cipher_algorithm_mismatch")
        payload = self.cipher.decrypt(envelope.ciphertext, envelope.associated_data, envelope.key_id)
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), envelope.digest):
            raise ValueError("sync_payload_digest_mismatch")
        return payload


__all__ = [
    "EncryptedSyncCodec",
    "EncryptedSyncEnvelope",
    "StageEvent",
    "StagePort",
    "StageSession",
    "SyncCipher",
    "SyncEncryptionUnavailable",
]

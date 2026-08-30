"""Durable, non-secret trust metadata for executable skill signing keys."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from ..core.paths import data_dir_from_env
from .skill_manifest import SignatureVerifier, SkillManifest, verify_skill_package

SKILL_TRUST_SCHEMA_VERSION = "yuizaki.skill-trust.v1"
_MAX_EVENTS = 200
_KEY_FIELDS = {"keyId", "label", "status", "createdAt", "revokedAt", "reason", "replacedBy"}
_EVENT_FIELDS = {"timestamp", "action", "keyId", "detail"}
_EVENT_ACTIONS = {"register", "revoke", "rotate"}


class SkillTrustError(ValueError):
    """Raised for invalid or unsafe trust-store mutations."""


def _finite_timestamp(value: Any, *, allow_zero: bool = True) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result > 10**12 or (result < 0 or (not allow_zero and result == 0)):
        return None
    return result


def _sanitize_key(raw: Any) -> TrustedSkillKey | None:
    if not isinstance(raw, dict) or set(raw) - _KEY_FIELDS or not {"keyId", "status", "createdAt"}.issubset(raw):
        return None
    key_id = raw.get("keyId")
    status = raw.get("status")
    created_at = _finite_timestamp(raw.get("createdAt"))
    if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", key_id):
        return None
    if status not in {"active", "revoked"} or created_at is None:
        return None
    revoked_raw = raw.get("revokedAt")
    revoked_at = None if revoked_raw is None else _finite_timestamp(revoked_raw, allow_zero=False)
    if status == "revoked" and revoked_at is None:
        return None
    if status == "active" and revoked_raw is not None:
        return None
    label = raw.get("label", "")
    reason = raw.get("reason")
    replaced_by = raw.get("replacedBy")
    if not isinstance(label, str) or len(label) > 160:
        return None
    if reason is not None and (not isinstance(reason, str) or len(reason) > 240):
        return None
    if replaced_by is not None and (not isinstance(replaced_by, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", replaced_by)):
        return None
    return TrustedSkillKey(key_id=key_id, label=label, status=status, created_at=created_at,
                           revoked_at=revoked_at, reason=reason, replaced_by=replaced_by)


def _sanitize_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or set(raw) - _EVENT_FIELDS or not _EVENT_FIELDS.issubset(raw):
        return None
    timestamp = _finite_timestamp(raw.get("timestamp"))
    action = raw.get("action")
    key_id = raw.get("keyId")
    detail = raw.get("detail")
    if timestamp is None or action not in _EVENT_ACTIONS or not isinstance(key_id, str):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", key_id) or not isinstance(detail, str) or len(detail) > 240:
        return None
    return {"timestamp": timestamp, "action": action, "keyId": key_id, "detail": detail}


@dataclass(frozen=True)
class TrustedSkillKey:
    key_id: str
    label: str = ""
    status: str = "active"
    created_at: float = 0.0
    revoked_at: float | None = None
    reason: str | None = None
    replaced_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyId": self.key_id,
            "label": self.label,
            "status": self.status,
            "createdAt": self.created_at,
            "revokedAt": self.revoked_at,
            "reason": self.reason,
            "replacedBy": self.replaced_by,
        }


class SkillTrustStore:
    """Store key IDs and revocation state; private keys never enter this store."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "skill_trust.json"
        self._keys: dict[str, TrustedSkillKey] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = RLock()
        self._load()

    @staticmethod
    def _validate_key_id(value: str) -> str:
        key_id = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", key_id):
            raise SkillTrustError("invalid skill signing key id")
        return key_id

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schemaVersion") != SKILL_TRUST_SCHEMA_VERSION:
                self._keys = {}
                self._events = []
                return
            raw_keys = payload.get("keys") if isinstance(payload, dict) else None
            if isinstance(raw_keys, list):
                for raw in raw_keys:
                    key = _sanitize_key(raw)
                    if key is not None:
                        self._keys[key.key_id] = key
            raw_events = payload.get("events") if isinstance(payload, dict) else None
            if isinstance(raw_events, list):
                self._events = [item for item in (_sanitize_event(raw) for raw in raw_events) if item is not None][-_MAX_EVENTS:]
        except (OSError, TypeError, ValueError):
            self._keys = {}
            self._events = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": SKILL_TRUST_SCHEMA_VERSION,
            "keys": [item.to_dict() for item in self._keys.values()],
            "events": self._events[-_MAX_EVENTS:],
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.path)

    def _event(self, action: str, key_id: str, detail: str = "") -> None:
        self._events.append({"timestamp": time.time(), "action": action, "keyId": key_id[:160], "detail": detail[:240]})
        self._events = self._events[-_MAX_EVENTS:]

    def register(self, key_id: str, *, label: str = "") -> TrustedSkillKey:
        normalized = self._validate_key_id(key_id)
        with self._lock:
            existing = self._keys.get(normalized)
            if existing is not None:
                if existing.status == "active":
                    return existing
                raise SkillTrustError("revoked signing key cannot be reactivated")
            key = TrustedSkillKey(key_id=normalized, label=str(label).strip()[:160], created_at=time.time())
            self._keys[normalized] = key
            self._event("register", normalized)
            self._save()
            return key

    def revoke(self, key_id: str, *, reason: str, replaced_by: str | None = None) -> TrustedSkillKey:
        normalized = self._validate_key_id(key_id)
        clean_reason = str(reason).strip()[:240]
        if not clean_reason:
            raise SkillTrustError("revocation reason is required")
        with self._lock:
            existing = self._keys.get(normalized)
            if existing is None:
                raise SkillTrustError("unknown signing key")
            if existing.status == "revoked":
                return existing
            replacement = self._validate_key_id(replaced_by) if replaced_by else None
            revoked = TrustedSkillKey(
                key_id=existing.key_id,
                label=existing.label,
                status="revoked",
                created_at=existing.created_at,
                revoked_at=time.time(),
                reason=clean_reason,
                replaced_by=replacement,
            )
            self._keys[normalized] = revoked
            self._event("revoke", normalized, clean_reason)
            self._save()
            return revoked

    def rotate(self, old_key_id: str, new_key_id: str, *, label: str = "", reason: str = "rotated") -> TrustedSkillKey:
        with self._lock:
            old_id = self._validate_key_id(old_key_id)
            old_key = self._keys.get(old_id)
            if old_key is None:
                raise SkillTrustError("unknown signing key")
            if old_key.status == "revoked":
                raise SkillTrustError("revoked signing key cannot be rotated")
            new_id = self._validate_key_id(new_key_id)
            if new_id in self._keys:
                raise SkillTrustError("replacement signing key already exists")
            clean_reason = str(reason).strip()[:240]
            if not clean_reason:
                raise SkillTrustError("rotation reason is required")
            now = time.time()
            new_key = TrustedSkillKey(key_id=new_id, label=str(label).strip()[:160], created_at=now)
            self._keys[new_id] = new_key
            self._keys[old_id] = TrustedSkillKey(
                key_id=old_key.key_id,
                label=old_key.label,
                status="revoked",
                created_at=old_key.created_at,
                revoked_at=now,
                reason=clean_reason,
                replaced_by=new_id,
            )
            self._event("rotate", old_id, f"replaced_by={new_id}")
            self._save()
            return new_key

    def is_active(self, key_id: str | None) -> bool:
        with self._lock:
            return bool(key_id and self._keys.get(str(key_id).strip(), TrustedSkillKey("", status="revoked")).status == "active")

    def wrap_verifier(self, verifier: SignatureVerifier | None) -> SignatureVerifier:
        """Require an active key ID before invoking the cryptographic verifier."""
        def _verify(canonical: bytes, signature: str, key_id: str | None) -> bool:
            if not self.is_active(key_id) or verifier is None:
                return False
            try:
                return bool(verifier(canonical, signature, key_id))
            except Exception:  # noqa: BLE001 - verifier failures must fail closed
                return False

        return _verify

    def verify_manifest(
        self,
        manifest: SkillManifest,
        package_bytes: bytes,
        *,
        runtime_version: str,
        verifier: SignatureVerifier | None,
    ) -> dict[str, Any]:
        return verify_skill_package(
            manifest,
            package_bytes,
            runtime_version=runtime_version,
            verifier=self.wrap_verifier(verifier),
            require_signature=True,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schemaVersion": SKILL_TRUST_SCHEMA_VERSION,
                "keys": [item.to_dict() for item in self._keys.values()],
                "events": [dict(item) for item in self._events[-20:]],
            }


__all__ = ["SKILL_TRUST_SCHEMA_VERSION", "SkillTrustError", "SkillTrustStore", "TrustedSkillKey"]

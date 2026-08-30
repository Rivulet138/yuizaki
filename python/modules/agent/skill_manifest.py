"""Verification primitives for executable skill packages.

The verifier deliberately receives a package byte stream and a caller-owned
signature verifier.  It does not load code, invoke a skill, or grant a
permission receipt; those responsibilities remain in the runtime and policy
layers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class SkillManifestError(ValueError):
    """Raised when a skill manifest cannot prove package identity or trust."""


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    version: str
    checksum_sha256: str
    runtime_binding: str
    scopes: tuple[str, ...] = ()
    signature: str | None = None
    key_id: str | None = None
    min_runtime: str | None = None
    max_runtime: str | None = None

    def canonical_bytes(self) -> bytes:
        payload = {
            "skill_id": self.skill_id,
            "version": self.version,
            "checksum_sha256": self.checksum_sha256,
            "runtime_binding": self.runtime_binding,
            "scopes": list(self.scopes),
            "key_id": self.key_id,
            "min_runtime": self.min_runtime,
            "max_runtime": self.max_runtime,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


SignatureVerifier = Callable[[bytes, str, str | None], bool]


def _version_key(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    if not parts:
        raise SkillManifestError("invalid runtime version")
    return tuple(int(part) for part in parts[:4])


def verify_skill_package(
    manifest: SkillManifest,
    package_bytes: bytes,
    *,
    runtime_version: str,
    verifier: SignatureVerifier | None,
    require_signature: bool = True,
) -> dict[str, Any]:
    """Verify package identity, signature policy and runtime compatibility."""
    if not isinstance(package_bytes, bytes):
        raise SkillManifestError("skill package must be bytes")
    if (
        not isinstance(manifest.skill_id, str)
        or not isinstance(manifest.version, str)
        or not isinstance(manifest.runtime_binding, str)
        or not manifest.skill_id.strip()
        or not manifest.version.strip()
        or not manifest.runtime_binding.strip()
    ):
        raise SkillManifestError("skill identity and runtime binding are required")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", manifest.skill_id):
        raise SkillManifestError("invalid skill id")
    if len(manifest.version) > 64 or len(manifest.runtime_binding) > 160:
        raise SkillManifestError("skill version or runtime binding is too long")
    if not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}", manifest.runtime_binding):
        raise SkillManifestError("invalid runtime binding")
    if not isinstance(manifest.checksum_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", manifest.checksum_sha256):
        raise SkillManifestError("invalid skill checksum")
    if manifest.signature is not None and (
        not isinstance(manifest.signature, str) or len(manifest.signature) > 8192
    ):
        raise SkillManifestError("invalid skill signature")
    if manifest.key_id is not None and (
        not isinstance(manifest.key_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", manifest.key_id)
    ):
        raise SkillManifestError("invalid signing key id")
    if not isinstance(manifest.scopes, (tuple, list)) or len(manifest.scopes) > 32 or any(
        not isinstance(scope, str) or not scope.strip() or len(scope) > 160
        for scope in manifest.scopes
    ):
        raise SkillManifestError("invalid skill scopes")
    actual_checksum = hashlib.sha256(package_bytes).hexdigest()
    if actual_checksum.lower() != manifest.checksum_sha256.lower():
        raise SkillManifestError("skill checksum mismatch")
    if require_signature and (not manifest.signature or verifier is None):
        raise SkillManifestError("signed skill verifier is required")
    if manifest.signature and verifier is not None and not verifier(
        manifest.canonical_bytes(), manifest.signature, manifest.key_id
    ):
        raise SkillManifestError("skill signature rejected")
    runtime_key = _version_key(runtime_version)
    for bound, relation in ((manifest.min_runtime, "min"), (manifest.max_runtime, "max")):
        if bound and ((relation == "min" and runtime_key < _version_key(bound)) or (relation == "max" and runtime_key > _version_key(bound))):
            raise SkillManifestError("skill runtime compatibility mismatch")
    return {
        "skillId": manifest.skill_id,
        "version": manifest.version,
        "runtimeBinding": manifest.runtime_binding,
        "scopes": list(manifest.scopes),
        "checksumSha256": actual_checksum,
        "signed": bool(manifest.signature),
        "runtimeVersion": runtime_version,
    }


__all__ = ["SignatureVerifier", "SkillManifest", "SkillManifestError", "verify_skill_package"]

"""Signed plugin package verification primitives.

The package loader supplies a reviewed signature verifier (for example an
Ed25519 implementation). This module owns canonicalization, checksum and
compatibility policy without embedding cryptography or silently accepting
unsigned production packages.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


class PluginTrustError(ValueError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    checksum_sha256: str
    signature: str | None = None
    key_id: str | None = None
    min_runtime: str | None = None
    max_runtime: str | None = None

    def canonical_bytes(self) -> bytes:
        payload = {
            "plugin_id": self.plugin_id,
            "version": self.version,
            "checksum_sha256": self.checksum_sha256,
            "key_id": self.key_id,
            "min_runtime": self.min_runtime,
            "max_runtime": self.max_runtime,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


SignatureVerifier = Callable[[bytes, str, str | None], bool]


def _version_key(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    if not parts:
        raise PluginTrustError("invalid runtime version")
    return tuple(int(part) for part in parts[:4])


def verify_plugin_package(
    manifest: PluginManifest,
    package_bytes: bytes,
    *,
    runtime_version: str,
    verifier: SignatureVerifier | None,
    require_signature: bool = True,
) -> dict[str, Any]:
    if not manifest.plugin_id.strip() or not manifest.version.strip():
        raise PluginTrustError("plugin identity is required")
    actual_checksum = hashlib.sha256(package_bytes).hexdigest()
    if actual_checksum.lower() != manifest.checksum_sha256.lower():
        raise PluginTrustError("plugin checksum mismatch")
    if require_signature and (not manifest.signature or verifier is None):
        raise PluginTrustError("signed plugin verifier is required")
    if manifest.signature and verifier is not None and not verifier(
        manifest.canonical_bytes(), manifest.signature, manifest.key_id
    ):
        raise PluginTrustError("plugin signature rejected")
    runtime_key = _version_key(runtime_version)
    for bound, relation in ((manifest.min_runtime, "min"), (manifest.max_runtime, "max")):
        if bound and ((relation == "min" and runtime_key < _version_key(bound)) or (relation == "max" and runtime_key > _version_key(bound))):
            raise PluginTrustError("plugin runtime compatibility mismatch")
    return {
        "pluginId": manifest.plugin_id,
        "version": manifest.version,
        "checksumSha256": actual_checksum,
        "signed": bool(manifest.signature),
        "runtimeVersion": runtime_version,
    }


__all__ = ["PluginManifest", "PluginTrustError", "verify_plugin_package"]

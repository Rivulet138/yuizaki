from __future__ import annotations

import hashlib

import pytest

from modules.agent.plugin_trust import PluginManifest, PluginTrustError, verify_plugin_package
from modules.system.capability_wizard import CapabilityCheck, build_capability_snapshot


def test_capability_wizard_exposes_repair_path_and_required_readiness() -> None:
    snapshot = build_capability_snapshot([
        CapabilityCheck("llm", "LLM", "ready", "ready", required=True),
        CapabilityCheck("microphone", "Microphone", "degraded", "permission required", "open_permissions"),
    ])
    assert snapshot.status == "degraded"
    assert snapshot.ready is True
    assert snapshot.to_dict()["checks"][1]["repairAction"] == "open_permissions"


def test_plugin_trust_requires_checksum_and_signature() -> None:
    package = b"plugin-package"
    manifest = PluginManifest("demo", "1.0.0", hashlib.sha256(package).hexdigest(), signature="ok", key_id="k1")
    assert verify_plugin_package(manifest, package, runtime_version="1.0.0", verifier=lambda *_: True)["signed"] is True
    with pytest.raises(PluginTrustError, match="verifier"):
        verify_plugin_package(manifest, package, runtime_version="1.0.0", verifier=None)
    with pytest.raises(PluginTrustError, match="checksum"):
        verify_plugin_package(manifest, b"tampered", runtime_version="1.0.0", verifier=lambda *_: True)

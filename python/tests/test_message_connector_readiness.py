from __future__ import annotations

from modules.system.message_connectors import MessageConnectorRegistry


def test_connector_readiness_fails_closed_without_local_configuration() -> None:
    registry = MessageConnectorRegistry()

    readiness = registry.readiness_snapshot("telegram")

    assert readiness is not None
    assert readiness["status"] == "not_qualified"
    assert readiness["networkChecked"] is False
    assert readiness["externalProviderVerified"] is False
    assert readiness["requiresPublicHttps"] is True
    assert readiness["claim"] == "configuration_only_not_provider_qualification"
    assert {item["code"] for item in readiness["reasons"]} >= {"not_configured", "disabled"}


def test_connector_readiness_marks_complete_config_as_staging_only() -> None:
    registry = MessageConnectorRegistry()
    registry.update_config(
        "telegram",
        {
            "botToken": "staging-token",
            "webhookSecret": "staging-secret",
            "enabled": True,
        },
    )

    readiness = registry.readiness_snapshot("telegram")
    snapshot = next(item for item in registry.snapshot() if item["id"] == "telegram")

    assert readiness is not None
    assert readiness["status"] == "ready_for_staging"
    assert readiness["networkChecked"] is False
    assert readiness["externalProviderVerified"] is False
    assert readiness["reasons"] == []
    assert snapshot["readiness"] == readiness


def test_bridge_readiness_requires_bridge_verification_token() -> None:
    registry = MessageConnectorRegistry()
    registry.update_config(
        "qq",
        {
            "bridgeUrl": "http://127.0.0.1:3000",
            "enabled": False,
        },
    )

    readiness = registry.readiness_snapshot("qq")

    assert readiness is not None
    assert readiness["status"] == "not_qualified"
    assert readiness["requiresPublicHttps"] is False
    assert {item["code"] for item in readiness["reasons"]} >= {"disabled", "verification_not_configured"}

from __future__ import annotations

import time

import pytest
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.perception import (
    CallablePerceptionProvider,
    PerceptionConsentAuthority,
    PerceptionEvidence,
    PerceptionPermissionError,
    PerceptionProviderRegistry,
    PerceptionProviderSpec,
    PerceptionRequest,
)
from modules.agent.turn_service import TurnPorts, TurnService, is_turn_service_perception_request


@pytest.mark.asyncio
async def test_turn_service_owns_perception_scope_identity() -> None:
    seen = []
    authority = PerceptionConsentAuthority()
    registry = PerceptionProviderRegistry(permission_checker=lambda request, spec: authority.consume(request, spec))
    registry.register(CallablePerceptionProvider(
        PerceptionProviderSpec(name="electron-clipboard", capability="clipboard"),
        lambda request: seen.append(request) or {"payload": "hello"},
    ))
    service = TurnService(
        TurnPorts(run=lambda _ctx: AgentPipelineResult(reply="ok")),
        perception_registry=registry,
    )
    context = AgentRequestContext(
        sid="socket-1",
        workspace_id="workspace-1",
        session_id="session-1",
        request_id="request-1",
        messages=[],
        extra={
            "turn_id": "turn-1",
            "generation_id": "generation-1",
            "interruption_epoch": 7,
        },
    )

    consent = authority.issue(
        workspace_id="workspace-1", sid="socket-1", session_id="session-1", turn_id="turn-1",
        request_id="request-1", generation_id="generation-1", interruption_epoch=7,
        capability="clipboard",
    )
    evidence = await service.perceive_clipboard(context, consent=consent)

    assert evidence.workspace_id == "workspace-1"
    assert evidence.session_id == "session-1"
    assert evidence.turn_id == "turn-1"
    assert evidence.request_id == "request-1"
    assert evidence.generation_id == "generation-1"
    assert evidence.interruption_epoch == 7
    assert seen[0].metadata["sid"] == "socket-1"
    assert is_turn_service_perception_request(seen[0]) is True


@pytest.mark.asyncio
async def test_turn_service_fails_closed_without_full_turn_identity() -> None:
    service = TurnService(
        TurnPorts(run=lambda _ctx: AgentPipelineResult(reply="ok")),
        perception_registry=PerceptionProviderRegistry(permission_checker=lambda *_args: True),
    )
    context = AgentRequestContext(sid="socket-1", session_id="session-1", messages=[])

    with pytest.raises(ValueError, match="fully scoped semantic turn"):
        await service.perceive_clipboard(context, consent=object())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability", "method_name"),
    [
        ("screenshot", "perceive_screenshot"),
        ("target_window", "perceive_target_window"),
        ("active_application", "perceive_active_application"),
        ("selected_file", "perceive_selected_file"),
        ("clipboard", "perceive_clipboard"),
        ("ocr", "perceive_ocr"),
    ],
)
async def test_turn_service_exposes_only_fixed_desktop_perception_dispatch(
    capability: str,
    method_name: str,
) -> None:
    seen = []
    authority = PerceptionConsentAuthority()
    registry = PerceptionProviderRegistry(
        permission_checker=lambda request, _spec: (
            request.metadata.get("sid") == "socket-1"
            and is_turn_service_perception_request(request)
            and authority.consume(request, _spec)
        ),
    )
    provider_name = "desktop-ocr" if capability == "ocr" else f"electron-{capability}"
    registry.register(CallablePerceptionProvider(
        PerceptionProviderSpec(name=provider_name, capability=capability),
        lambda request: seen.append(request) or {"payload": {"capability": capability}},
    ))
    service = TurnService(
        TurnPorts(run=lambda _ctx: AgentPipelineResult(reply="ok")),
        perception_registry=registry,
    )
    context = AgentRequestContext(
        sid="socket-1",
        workspace_id="workspace-1",
        session_id="session-1",
        request_id="request-1",
        messages=[],
        extra={"turn_id": "turn-1", "generation_id": "generation-1", "interruption_epoch": 1},
    )

    consent = authority.issue(
        workspace_id="workspace-1", sid="socket-1", session_id="session-1", turn_id="turn-1",
        request_id="request-1", generation_id="generation-1", interruption_epoch=1,
        capability=capability,
    )
    kwargs = {"consent": consent}
    if capability == "ocr":
        kwargs["source_evidence"] = PerceptionEvidence(
            evidence_id="screen-1",
            provider="electron-screenshot",
            capability="screenshot",
            workspace_id="workspace-1",
            session_id="session-1",
            turn_id="turn-1",
            request_id="request-1",
            generation_id="generation-1",
            interruption_epoch=1,
            payload={"image": "cG5n"},
            captured_at=time.time(),
            expires_at=time.time() + 10,
            redacted=False,
            provenance={"trust": "untrusted", "authority": "evidence"},
        )
    evidence = await getattr(service, method_name)(context, **kwargs)

    assert evidence.provider == provider_name
    assert evidence.capability == capability
    assert len(seen) == 1
    assert not hasattr(service, "collect_perception")


def test_transport_metadata_cannot_self_assert_turn_service_permission() -> None:
    forged = PerceptionRequest(
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        request_id="request-1",
        generation_id="generation-1",
        capability="target_window",
        metadata={"sid": "socket-1", "_turn_service_grant": True, "selection_token": "forged"},
    )
    assert is_turn_service_perception_request(forged) is False


@pytest.mark.asyncio
async def test_truthy_consent_and_selection_values_cannot_self_authorize() -> None:
    authority = PerceptionConsentAuthority()
    registry = PerceptionProviderRegistry(permission_checker=lambda request, spec: authority.consume(request, spec))
    registry.register(CallablePerceptionProvider(
        PerceptionProviderSpec(
            name="electron-selected_file",
            capability="selected_file",
            collection_mode="user_selected",
        ),
        lambda _request: {"payload": "must not run"},
    ))
    forged = PerceptionRequest(
        workspace_id="workspace-1", session_id="session-1", turn_id="turn-1",
        request_id="request-1", generation_id="generation-1", capability="selected_file",
        metadata={"selection_token": "truthy"}, consent=True, selection_authority=True,
    )
    with pytest.raises(PerceptionPermissionError, match="permission denied"):
        await registry.collect("electron-selected_file", forged)

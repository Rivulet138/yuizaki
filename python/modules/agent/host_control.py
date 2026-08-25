"""Authenticated host-only control routes for computer-use fencing."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..system.backend_api_auth import (
    HOST_DESKTOP_ACTION_TOKEN_ENV,
    verify_host_desktop_action_authorization,
)


class EmergencyStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class DesktopFeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_ttl_seconds: float = Field(default=5.0, gt=0, le=30)


class DesktopHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_epoch: int = Field(ge=1)
    lease_ttl_seconds: float = Field(default=5.0, gt=0, le=30)


class DesktopDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_seconds: float = Field(default=15.0, gt=0, le=15)


class DesktopAppGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: str = Field(min_length=16, max_length=128)
    discovery_revision: int = Field(ge=1)
    allowed_actions: list[str] = Field(min_length=1, max_length=2)
    ttl_seconds: float = Field(default=30.0, gt=0, le=300)


def create_computer_use_host_router(
    *,
    stop: Callable[[], dict[str, Any]],
    status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/computer-use", tags=["computer-use-host"])

    async def _computer_use_status() -> dict[str, Any]:
        return {"ok": True, **status()}

    async def _computer_use_emergency_stop(request: EmergencyStopRequest) -> dict[str, Any]:
        try:
            return {"ok": True, **stop()}
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "CU_SCOPE_REJECTED", "message": "computer-use scope was rejected"},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "CU_CONTROLLER_UNAVAILABLE", "message": "computer-use controller unavailable"},
            ) from exc

    async def _computer_use_preview(_request: PreviewRequest) -> dict[str, Any]:
        # Host previews require an issued action session and bound AgentRequestContext.
        # HTTP callers cannot synthesize those authorities or bypass ToolRegistry.
        return {
            "ok": False,
            "code": "CU_PREVIEW_UNAVAILABLE",
            "message": "host preview is unavailable outside computer.preview_action",
        }

    router.add_api_route("/status", _computer_use_status, methods=["GET"])
    router.add_api_route("/emergency-stop", _computer_use_emergency_stop, methods=["POST"])
    router.add_api_route("/preview", _computer_use_preview, methods=["POST"], status_code=503)
    return router


def create_desktop_action_host_router(
    *,
    status: Callable[[], dict[str, Any]],
    enable: Callable[[], dict[str, Any]],
    disable: Callable[[], dict[str, Any]],
    rearm: Callable[[], dict[str, Any]],
    stop: Callable[[], dict[str, Any]],
    heartbeat: Callable[..., dict[str, Any]] | None = None,
    discover: Callable[..., dict[str, Any]] | None = None,
    grant: Callable[..., dict[str, Any]] | None = None,
    host_token_provider: Callable[[], str] | None = None,
    backend_token_provider: Callable[[], str] | None = None,
) -> APIRouter:
    """Expose only feature-state controls to the authenticated desktop host.

    Target discovery, previews, and effects are intentionally absent: those
    operations require a private AgentRequestContext binding and ToolExecutor.
    """

    router = APIRouter(prefix="/api/desktop-actions", tags=["desktop-actions-host"])

    resolved_host_token = host_token_provider or (lambda: os.getenv(HOST_DESKTOP_ACTION_TOKEN_ENV, ""))
    resolved_backend_token = backend_token_provider or (lambda: "")

    def guarded(
        callback: Callable[..., dict[str, Any]],
        authorization: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        allowed, message = verify_host_desktop_action_authorization(
            authorization,
            resolved_host_token(),
            resolved_backend_token(),
        )
        if not allowed:
            raise HTTPException(
                status_code=401,
                detail={"code": "DA_HOST_UNAUTHORIZED", "message": message},
            )
        try:
            return {"ok": True, **callback(**kwargs)}
        except (ValueError, RuntimeError) as exc:
            code = getattr(exc, "code", "DA_STATE_REJECTED")
            status_code = 503 if code in {"DA_CONTROLLER_UNAVAILABLE", "DA_ADAPTER_FAILURE"} else 409
            raise HTTPException(
                status_code=status_code,
                detail={"code": code, "message": "desktop action request was rejected"},
            ) from exc

    async def feature_status(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return guarded(status, authorization)

    async def feature_enable(_request: DesktopFeatureRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return guarded(enable, authorization, lease_ttl_seconds=_request.lease_ttl_seconds)

    async def feature_disable(_request: DesktopFeatureRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return guarded(disable, authorization)

    async def feature_rearm(_request: DesktopFeatureRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return guarded(rearm, authorization, lease_ttl_seconds=_request.lease_ttl_seconds)

    async def feature_stop(_request: DesktopFeatureRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return guarded(stop, authorization)

    async def feature_heartbeat(request: DesktopHeartbeatRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        if heartbeat is None:
            raise HTTPException(status_code=503, detail={"code": "DA_CONTROLLER_UNAVAILABLE"})
        return guarded(
            heartbeat,
            authorization,
            lease_epoch=request.lease_epoch,
            lease_ttl_seconds=request.lease_ttl_seconds,
        )

    async def host_discovery(request: DesktopDiscoveryRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        if discover is None:
            raise HTTPException(status_code=503, detail={"code": "DA_CONTROLLER_UNAVAILABLE"})
        return guarded(
            discover,
            authorization,
            ttl_seconds=request.ttl_seconds,
            identity_secret=resolved_host_token(),
        )

    async def host_grant(request: DesktopAppGrantRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        if grant is None:
            raise HTTPException(status_code=503, detail={"code": "DA_CONTROLLER_UNAVAILABLE"})
        return guarded(
            grant,
            authorization,
            app_id=request.app_id,
            discovery_revision=request.discovery_revision,
            allowed_actions=request.allowed_actions,
            ttl_seconds=request.ttl_seconds,
        )

    async def unavailable_preview(_request: DesktopFeatureRequest, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        allowed, message = verify_host_desktop_action_authorization(
            authorization, resolved_host_token(), resolved_backend_token(),
        )
        if not allowed:
            raise HTTPException(
                status_code=401,
                detail={"code": "DA_HOST_UNAUTHORIZED", "message": message},
            )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DA_HOST_BINDING_REQUIRED",
                "message": "desktop previews require a trusted turn context",
            },
        )

    router.add_api_route("/status", feature_status, methods=["GET"])
    router.add_api_route("/enable", feature_enable, methods=["POST"])
    router.add_api_route("/disable", feature_disable, methods=["POST"])
    router.add_api_route("/rearm", feature_rearm, methods=["POST"])
    router.add_api_route("/emergency-stop", feature_stop, methods=["POST"])
    router.add_api_route("/heartbeat", feature_heartbeat, methods=["POST"])
    router.add_api_route("/discover", host_discovery, methods=["POST"])
    router.add_api_route("/grant", host_grant, methods=["POST"])
    router.add_api_route("/preview", unavailable_preview, methods=["POST"])
    return router

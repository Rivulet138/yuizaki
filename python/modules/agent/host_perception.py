"""Authorized host perception adapters.

Collectors are transport ports implemented by the trusted desktop host. Their
output remains untrusted evidence and is fully revalidated by the registry.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .perception import (
    PerceptionProviderSpec,
    PerceptionRequest,
)


class HostPerceptionCollector(Protocol):
    async def collect(self, request: PerceptionRequest) -> dict[str, Any]: ...


@dataclass
class CallableHostPerceptionCollector:
    callback: Callable[[PerceptionRequest], dict[str, Any] | Awaitable[dict[str, Any]]]

    async def collect(self, request: PerceptionRequest) -> dict[str, Any]:
        result = self.callback(request)
        return await result if inspect.isawaitable(result) else result


@dataclass
class AuthorizedHostPerceptionProvider:
    spec: PerceptionProviderSpec
    collector: HostPerceptionCollector

    def __post_init__(self) -> None:
        if not self.spec.requires_host_provenance:
            raise ValueError("authorized host providers require host provenance validation")
        if self.spec.collection_mode not in {"request", "user_selected"}:
            raise ValueError("authorized host providers must be request scoped")

    async def collect(self, request: PerceptionRequest) -> dict[str, Any]:
        return await self.collector.collect(request)


def authorized_host_spec(
    *,
    name: str,
    capability: str,
    user_selected: bool = False,
    ttl_seconds: float = 15.0,
    max_payload_bytes: int = 2_000_000,
) -> PerceptionProviderSpec:
    return PerceptionProviderSpec(
        name=name,
        capability=capability,
        requires_permission=True,
        collection_mode="user_selected" if user_selected else "request",
        ttl_seconds=ttl_seconds,
        max_payload_bytes=max_payload_bytes,
        supports_redaction=True,
        storage_policy="ephemeral",
        requires_host_provenance=True,
    )

"""Opt-in authenticated transport boundary for redacted product metrics."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Self
from urllib.parse import urlparse

import httpx

ProductEvent = Mapping[str, object]
_IDEMPOTENCY_KEY = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ProductBatchReceipt:
    """Server acknowledgement for one idempotent export batch."""

    schema_version: int
    idempotency_key: str
    event_count: int
    status: str


def parse_product_batch_receipt(
    value: object,
    *,
    expected_key: str,
    expected_event_count: int,
) -> ProductBatchReceipt:
    """Validate that the server acknowledged the exact exported batch."""
    if not _IDEMPOTENCY_KEY.fullmatch(expected_key) or expected_event_count < 0:
        raise ValueError("product metrics batch receipt expectation is invalid")
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "idempotency_key", "event_count", "status",
    }:
        raise ValueError("product metrics batch receipt is invalid")
    schema_version = value["schema_version"]
    idempotency_key = value["idempotency_key"]
    event_count = value["event_count"]
    status = value["status"]
    if (schema_version != 1 or not isinstance(idempotency_key, str)
            or idempotency_key != expected_key
            or not isinstance(event_count, int) or isinstance(event_count, bool)
            or event_count != expected_event_count
            or status not in {"accepted", "duplicate"}):
        raise ValueError("product metrics batch receipt is invalid")
    return ProductBatchReceipt(schema_version, idempotency_key, event_count, status)


@dataclass(frozen=True)
class ProductDeletionReceipt:
    """Server acknowledgement proving one idempotent deletion request."""

    schema_version: int
    idempotency_key: str
    status: str


def parse_product_deletion_receipt(value: object, *, expected_key: str) -> ProductDeletionReceipt:
    """Validate a deletion receipt without trusting arbitrary response JSON."""
    if not _IDEMPOTENCY_KEY.fullmatch(expected_key):
        raise ValueError("product metrics idempotency key is invalid")
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "idempotency_key", "status"}:
        raise ValueError("product metrics deletion receipt is invalid")
    schema_version = value["schema_version"]
    idempotency_key = value["idempotency_key"]
    status = value["status"]
    if (schema_version != 1 or not isinstance(idempotency_key, str)
            or idempotency_key != expected_key
            or status not in {"deleted", "already_deleted"}):
        raise ValueError("product metrics deletion receipt is invalid")
    return ProductDeletionReceipt(schema_version, idempotency_key, status)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("product metrics endpoint must use an authenticated HTTPS origin")
    if parsed.query or parsed.fragment:
        raise ValueError("product metrics endpoint must not contain query or fragment")
    return f"https://{parsed.netloc.lower()}"


def _validate_endpoint(url: str, allowed_origins: frozenset[str]) -> str:
    origin = _origin(url)
    if origin not in allowed_origins:
        raise ValueError("product metrics endpoint origin is not allowlisted")
    return url


class HttpProductEventTransport:
    """Synchronous HTTPS transport with auth, bounded retries, and deletion.

    This adapter is inert until an endpoint, allowlisted origin, and bearer
    token are explicitly supplied. It never falls back to HTTP or sends a
    token through a URL. A server must treat ``Idempotency-Key`` as the batch
    identity and expose a deletion endpoint before this is production-ready.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        allowed_origins: Iterable[str],
        bearer_token: str | Callable[[], str],
        delete_endpoint: str | None = None,
        timeout_seconds: float = 10.0,
        max_payload_bytes: int = 1_000_000,
        max_attempts: int = 3,
        require_batch_receipt: bool = False,
        require_deletion_receipt: bool = False,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0 or max_payload_bytes < 1 or not 1 <= max_attempts <= 5:
            raise ValueError("product metrics transport limits are invalid")
        normalized_origins = frozenset(_origin(origin).rstrip("/") for origin in allowed_origins)
        self.endpoint = _validate_endpoint(endpoint, normalized_origins)
        self.delete_endpoint = _validate_endpoint(delete_endpoint, normalized_origins) if delete_endpoint else None
        self.bearer_token = bearer_token
        self.timeout_seconds = timeout_seconds
        self.max_payload_bytes = max_payload_bytes
        self.max_attempts = max_attempts
        self.require_batch_receipt = require_batch_receipt
        self.require_deletion_receipt = require_deletion_receipt
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _authorization(self) -> str:
        token = self.bearer_token() if callable(self.bearer_token) else self.bearer_token
        if not isinstance(token, str) or not token.strip() or any(char.isspace() for char in token):
            raise ValueError("product metrics bearer token is invalid")
        return f"Bearer {token.strip()}"

    def _payload(self, events: Sequence[ProductEvent]) -> bytes:
        payload = json.dumps({"events": list(events)}, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > self.max_payload_bytes:
            raise ValueError("product metrics payload exceeds configured limit")
        return payload

    def _request(self, method: str, url: str, *, idempotency_key: str, content: bytes | None = None) -> httpx.Response:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ValueError("product metrics idempotency key is invalid")
        headers = {
            "Accept": "application/json",
            "Authorization": self._authorization(),
            "Idempotency-Key": idempotency_key,
        }
        if content is not None:
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                response = self._client.request(method, url, headers=headers, content=content)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt + 1 < self.max_attempts:
                    self._sleep(0.25 * (2**attempt))
                    continue
                raise RuntimeError("product metrics transport unavailable") from error
            if response.status_code in {200, 201, 202, 204, 409}:
                return response
            retryable = response.status_code == 408 or response.status_code == 429 or 500 <= response.status_code <= 599
            if retryable and attempt + 1 < self.max_attempts:
                self._sleep(0.25 * (2**attempt))
                continue
            raise RuntimeError(f"product metrics endpoint rejected request: HTTP {response.status_code}")
        raise RuntimeError("product metrics transport unavailable") from last_error

    def send_batch(self, events: Iterable[ProductEvent], *, idempotency_key: str) -> None:
        batch = tuple(events)
        response = self._request("POST", self.endpoint, idempotency_key=idempotency_key, content=self._payload(batch))
        if self.require_batch_receipt:
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError("product metrics batch receipt is missing") from error
            parse_product_batch_receipt(
                payload,
                expected_key=idempotency_key,
                expected_event_count=len(batch),
            )

    def send(self, events: Iterable[ProductEvent]) -> None:
        batch = tuple(events)
        canonical = json.dumps(batch, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_batch(batch, idempotency_key=sha256(canonical).hexdigest())

    def delete_batch(self, *, idempotency_key: str) -> None:
        if self.delete_endpoint is None:
            raise RuntimeError("product metrics deletion endpoint is not configured")
        response = self._request("DELETE", self.delete_endpoint, idempotency_key=idempotency_key)
        if self.require_deletion_receipt:
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError("product metrics deletion receipt is missing") from error
            parse_product_deletion_receipt(payload, expected_key=idempotency_key)


__all__ = [
    "HttpProductEventTransport",
    "ProductBatchReceipt",
    "ProductDeletionReceipt",
    "parse_product_batch_receipt",
    "parse_product_deletion_receipt",
]

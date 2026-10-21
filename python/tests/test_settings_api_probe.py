from __future__ import annotations

import socket

import pytest

from modules.system.settings_api import _safe_probe_url


def test_safe_probe_url_rejects_loopback_literal() -> None:
    with pytest.raises(ValueError, match="private or local"):
        _safe_probe_url("http://127.0.0.1:7861")


def test_safe_probe_url_rejects_private_dns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", 80))],
    )

    with pytest.raises(ValueError, match="private or local"):
        _safe_probe_url("http://svc.example.test")


def test_safe_probe_url_accepts_global_dns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )

    assert _safe_probe_url("http://svc.example.test:8080/path") == "http://svc.example.test:8080/path"


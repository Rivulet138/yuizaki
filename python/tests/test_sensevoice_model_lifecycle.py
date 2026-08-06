import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

from modules.asr.sensevoice import SenseVoiceClient


@pytest.mark.asyncio
async def test_sensevoice_connect_is_idempotent_under_concurrency(monkeypatch, tmp_path):
    loads = 0

    def auto_model(**_kwargs):
        nonlocal loads
        loads += 1
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    await asyncio.gather(client.connect(), client.connect(), client.connect())

    assert client.is_available
    assert loads == 1


@pytest.mark.asyncio
async def test_sensevoice_disconnect_releases_model_and_allows_reload(monkeypatch, tmp_path):
    loads = 0

    def auto_model(**_kwargs):
        nonlocal loads
        loads += 1
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    await client.connect()
    await client.disconnect()
    assert not client.is_available
    await client.connect()

    assert client.is_available
    assert loads == 2


@pytest.mark.asyncio
async def test_cancelled_connect_reuses_the_single_inflight_model_load(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    loads = 0

    def auto_model(**_kwargs):
        nonlocal loads
        loads += 1
        started.set()
        release.wait(timeout=5)
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    first = asyncio.create_task(client.connect())
    await asyncio.to_thread(started.wait, 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(client.connect())
    await asyncio.sleep(0)
    assert loads == 1
    release.set()
    await second

    assert client.is_available
    assert loads == 1


@pytest.mark.asyncio
async def test_disconnect_during_load_prevents_stale_install_and_reconnect_reuses_load(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    loads = 0

    def auto_model(**_kwargs):
        nonlocal loads
        loads += 1
        started.set()
        release.wait(timeout=5)
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    stale_connect = asyncio.create_task(client.connect())
    await asyncio.to_thread(started.wait, 2)
    await client.disconnect()
    reconnect = asyncio.create_task(client.connect())
    await asyncio.sleep(0)
    assert loads == 1

    release.set()
    await asyncio.gather(stale_connect, reconnect)

    assert client.is_available
    assert loads == 1


@pytest.mark.asyncio
async def test_cancelled_disconnected_load_releases_completed_task_without_reconnect(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def auto_model(**_kwargs):
        started.set()
        release.wait(timeout=5)
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    connect_task = asyncio.create_task(client.connect())
    await asyncio.to_thread(started.wait, 2)
    load_task = client._load_task
    assert load_task is not None
    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task
    await client.disconnect()

    release.set()
    await load_task
    await asyncio.sleep(0)

    assert client._load_task is None
    assert not client.is_available


@pytest.mark.asyncio
async def test_failed_background_load_is_retried_by_next_connect(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    loads = 0

    def auto_model(**_kwargs):
        nonlocal loads
        loads += 1
        if loads == 1:
            started.set()
            release.wait(timeout=5)
            raise RuntimeError("load failed")
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=auto_model))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    client = SenseVoiceClient()

    connect_task = asyncio.create_task(client.connect())
    await asyncio.to_thread(started.wait, 2)
    load_task = client._load_task
    assert load_task is not None
    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task
    release.set()
    with pytest.raises(RuntimeError, match="load failed"):
        await load_task
    await asyncio.sleep(0)

    await client.connect()

    assert client.is_available
    assert loads == 2

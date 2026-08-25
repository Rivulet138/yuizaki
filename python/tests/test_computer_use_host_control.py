from __future__ import annotations

import asyncio
from types import MethodType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent.computer_use import ComputerUseController
from modules.agent.host_control import create_computer_use_host_router
from modules.core.state import GenerationManager
from socket_server import DesktopPetSocketServer


def test_host_router_is_device_scoped_and_preview_is_explicitly_unavailable() -> None:
    app = FastAPI()
    stop_calls: list[None] = []
    app.include_router(create_computer_use_host_router(
        stop=lambda: stop_calls.append(None) or {"scope": "device", "revision": 1},
        status=lambda: {"scope": "device", "revision": 0, "stopped": False},
    ))
    client = TestClient(app)

    assert client.post("/api/computer-use/emergency-stop", json={}).json() == {
        "ok": True,
        "scope": "device",
        "revision": 1,
    }
    assert client.post("/api/computer-use/emergency-stop", json={"session_id": "leak"}).status_code == 422
    preview = client.post("/api/computer-use/preview", json={"actions": [{"type": "move", "x": 1, "y": 2}]})
    assert preview.status_code == 503
    assert preview.json()["code"] == "CU_PREVIEW_UNAVAILABLE"
    assert stop_calls == [None]


def test_device_stop_fences_controller_and_cancels_every_known_runtime_target() -> None:
    server = object.__new__(DesktopPetSocketServer)
    controller = ComputerUseController()
    generation_manager = GenerationManager()
    connected = generation_manager.start("connected")
    generation_only = generation_manager.start("generation-only")
    tool_signal = asyncio.Event()
    cleared: list[str] = []

    server.runtime = SimpleNamespace(computer_use_controller=controller)
    server.generation_mgr = generation_manager
    server.sessions = {"connected": {}}
    server._interruption_epoch = 0
    server._computer_use_last_stop_at = None
    server._computer_use_last_error = None
    server._visual_analysis_tasks = {"visual-only": SimpleNamespace(done=lambda: False)}
    server._latest_visual_frames = {}
    server._latest_visual_observations = {}
    server._visual_capture_requests = {"job": {"sid": "capture-only"}}
    server._tool_cancellation_signals = {"tool": ("tool-only", "request", tool_signal)}
    server._clear_visual_context = MethodType(lambda _self, sid: cleared.append(sid), server)

    result = server.emergency_stop_computer_use()

    assert result["scope"] == "device"
    assert result["revision"] == 1
    assert controller.stop_epoch == 1
    assert connected.invalidated is True
    assert generation_only.invalidated is True
    assert tool_signal.is_set()
    assert set(cleared) == {"connected", "generation-only", "visual-only", "capture-only", "tool-only"}

    second = server.emergency_stop_computer_use()
    assert second["revision"] == 2
    assert controller.stop_epoch == 2


def test_status_contains_no_session_or_authorization_material() -> None:
    server = object.__new__(DesktopPetSocketServer)
    server.runtime = SimpleNamespace(computer_use_controller=ComputerUseController())
    server._interruption_epoch = 2
    server._computer_use_last_stop_at = 123.0
    server._computer_use_last_error = "CU_CONTROLLER_UNAVAILABLE"

    status = server.computer_use_status()

    assert status["scope"] == "device"
    assert status["last_error"] == "CU_CONTROLLER_UNAVAILABLE"
    assert not ({"session_id", "token", "permit"} & set(status))

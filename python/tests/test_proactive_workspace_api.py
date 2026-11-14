from __future__ import annotations

from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.agent.activity_frames import ActivityFrameService, ActivityFrameStore
from modules.system.active_workspace_state import ActiveWorkspaceState
from modules.system.runtime_endpoints import build_activity_frame_endpoints
from routes.system_api import create_system_router

SETTINGS_PATH = "/api/system/proactive/settings"
FRAMES_PATH = "/api/system/activity-frames"
FEEDBACK_PATH = "/api/system/proactive/feedback"
SUMMARY_PATH = "/api/system/proactive/feedback-summary"
PATCH = {"expectedRevision": 0, "dnd": True}
FEEDBACK = {
    "feedbackId": "feedback-1",
    "jobId": "job-1",
    "requestId": "request-1",
    "sourceKind": "completed_turn_followup",
    "kind": "snoozed",
}
REQUESTS = [
    pytest.param("GET", SETTINGS_PATH, None, "get_settings", (), id="settings-get"),
    pytest.param("PATCH", SETTINGS_PATH, PATCH, "patch_settings", (PATCH,), id="settings-patch"),
    pytest.param("GET", FRAMES_PATH + "?limit=17", None, "list_frames", (17,), id="frames-list"),
    pytest.param("POST", FRAMES_PATH + "/rebuild", {"limit": 23}, "rebuild", (23,), id="frames-rebuild"),
    pytest.param("DELETE", FRAMES_PATH + "/frame-1", None, "delete_frame", ("frame-1",), id="frame-delete"),
    pytest.param("POST", FEEDBACK_PATH, FEEDBACK, "feedback", (FEEDBACK,), id="feedback"),
    pytest.param("GET", SUMMARY_PATH, None, "feedback_summary", (), id="feedback-summary"),
]


def _client(endpoints):
    app = FastAPI()
    app.include_router(create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        proactive_settings_get_handler=endpoints["get_settings"],
        proactive_settings_patch_handler=endpoints["patch_settings"],
        activity_frames_list_handler=endpoints["list_frames"],
        activity_frames_rebuild_handler=endpoints["rebuild"],
        activity_frame_delete_handler=endpoints["delete_frame"],
        proactive_feedback_handler=endpoints["feedback"],
        proactive_feedback_summary_handler=endpoints["feedback_summary"],
    ))
    return TestClient(app)


@pytest.fixture
def routed_service():
    service = Mock(spec=ActivityFrameService)
    for name in ("get_settings", "patch_settings", "list_frames", "rebuild", "feedback", "feedback_summary"):
        getattr(service, name).return_value = {"workspaceId": "workspace-a"}
    service.delete_frame.return_value = True
    active_provider = Mock(side_effect=AssertionError("HTTP endpoints must not resolve the active workspace"))
    endpoints = build_activity_frame_endpoints(
        service_provider=lambda: service,
        active_workspace_id_provider=active_provider,
    )
    with _client(endpoints) as client:
        yield client, service, active_provider


def test_settings_patch_stays_on_requested_workspace_when_active_switches_in_worker(tmp_path):
    store = ActivityFrameStore(tmp_path / "activity.sqlite3")
    service = ActivityFrameService(store, SimpleNamespace())
    active = ActiveWorkspaceState("workspace-a")
    caller_thread = get_ident()
    worker_threads = []

    def service_provider():
        worker_threads.append(get_ident())
        active.set("workspace-b")
        return service

    endpoints = build_activity_frame_endpoints(
        service_provider=service_provider,
        active_workspace_id_provider=active.get,
    )
    with _client(endpoints) as client:
        response = client.patch(SETTINGS_PATH, params={"workspace_id": "workspace-a"}, json=PATCH)
        assert response.status_code == 200, response.text
        assert active.get() == "workspace-b"
        assert worker_threads and all(thread != caller_thread for thread in worker_threads)
        assert response.json()["workspaceId"] == "workspace-a"
        assert response.json()["dnd"] is True
        assert response.json()["revision"] == 1

        saved_a, revision_a, _ = store.get_settings_record("workspace-a")
        saved_b, revision_b, _ = store.get_settings_record("workspace-b")
        assert (saved_a.dnd, revision_a) == (True, 1)
        assert (saved_b.dnd, revision_b) == (False, 0)

        read_a = client.get(SETTINGS_PATH, params={"workspace_id": "workspace-a"})
        read_b = client.get(SETTINGS_PATH, params={"workspace_id": "workspace-b"})
        assert read_a.status_code == read_b.status_code == 200
        assert read_a.json() == response.json()
        assert read_b.json()["workspaceId"] == "workspace-b"
        assert (read_b.json()["dnd"], read_b.json()["revision"]) == (False, 0)

        stale = client.patch(SETTINGS_PATH, params={"workspace_id": "workspace-a"}, json=PATCH)
        assert stale.status_code == 409
        assert store.get_settings_record("workspace-a")[1] == 1
        assert store.get_settings_record("workspace-b")[1] == 0


@pytest.mark.parametrize("method,path,payload,handler,args", REQUESTS)
def test_proactive_routes_forward_explicit_workspace(routed_service, method, path, payload, handler, args):
    client, service, active_provider = routed_service
    separator = "&" if "?" in path else "?"
    response = client.request(method, f"{path}{separator}workspace_id=workspace-a", json=payload)
    assert response.status_code == 200, response.text
    getattr(service, handler).assert_called_once_with("workspace-a", *args)
    active_provider.assert_not_called()


@pytest.mark.parametrize("workspace_id", [None, "", " \t", "bad workspace", "../workspace", "x" * 161])
@pytest.mark.parametrize("method,path,payload,handler,args", REQUESTS)
def test_proactive_routes_reject_missing_or_invalid_workspace(
    routed_service, method, path, payload, handler, args, workspace_id,
):
    client, service, active_provider = routed_service
    params = {} if workspace_id is None else {"workspace_id": workspace_id}
    response = client.request(method, path, params=params, json=payload)
    assert response.status_code == 422, response.text
    assert any(error["loc"] == ["query", "workspace_id"] for error in response.json()["detail"])
    assert service.mock_calls == []
    active_provider.assert_not_called()


@pytest.mark.parametrize("path,handler,limit", [(FRAMES_PATH, "list_frames", 50), (FRAMES_PATH + "/rebuild", "rebuild", 1000)])
def test_proactive_frame_routes_preserve_default_limits(routed_service, path, handler, limit):
    client, service, active_provider = routed_service
    method = "GET" if handler == "list_frames" else "POST"
    response = client.request(method, path, params={"workspace_id": "workspace-a"})
    assert response.status_code == 200, response.text
    getattr(service, handler).assert_called_once_with("workspace-a", limit)
    active_provider.assert_not_called()


@pytest.mark.parametrize("method,path,payload,handler,error,status", [
    ("PATCH", SETTINGS_PATH, PATCH, "patch_settings", LookupError("revision conflict"), 409),
    ("PATCH", SETTINGS_PATH, PATCH, "patch_settings", ValueError("invalid patch"), 422),
    ("POST", FRAMES_PATH + "/rebuild", {}, "rebuild", ValueError("invalid rebuild"), 422),
    ("DELETE", FRAMES_PATH + "/frame-1", None, "delete_frame", LookupError("not found"), 404),
    ("POST", FEEDBACK_PATH, FEEDBACK, "feedback", LookupError("not found"), 404),
])
def test_proactive_routes_preserve_error_statuses(routed_service, method, path, payload, handler, error, status):
    client, service, active_provider = routed_service
    getattr(service, handler).side_effect = error
    response = client.request(method, path, params={"workspace_id": "workspace-a"}, json=payload)
    assert response.status_code == status, response.text
    active_provider.assert_not_called()

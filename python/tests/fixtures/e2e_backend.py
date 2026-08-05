from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import io
import json
import os
import socket
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import socketio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse

PYTHON_ROOT = Path(__file__).resolve().parents[2]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

# Standalone fixture execution requires inserting the project package root first.
from modules.system.backend_api_auth import verify_backend_api_authorization  # noqa: E402


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "electron" / "src" / "shared" / "runtime-protocol-manifest.json"
TOKEN_HEADER = "X-Yuizaki-E2E-Token"


def _silent_wav_bytes(duration_ms: int = 180) -> bytes:
    sample_rate = 8_000
    frame_count = sample_rate * duration_ms // 1_000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * frame_count)
    return buffer.getvalue()


SILENT_WAV_BYTES = _silent_wav_bytes()


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


MANIFEST = load_manifest()
MANIFEST_HASH = hashlib.sha256(
    json.dumps(MANIFEST, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def match_protocol_payload(schema: dict[str, Any], value: Any) -> list[str]:
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        results = [match_protocol_payload(candidate, value) for candidate in one_of]
        matches = sum(not errors for errors in results)
        return [] if matches == 1 else [f"expected exactly one schema match, received {matches}"]
    if "const" in schema and value != schema["const"]:
        return [f"expected constant {schema['const']!r}"]
    expected_type = schema.get("type")
    actual_type = _value_type(value)
    if expected_type == "number" and actual_type == "integer":
        actual_type = "number"
    if expected_type and actual_type != expected_type:
        return [f"expected {expected_type}, received {actual_type}"]
    if expected_type != "object":
        return []
    errors: list[str] = []
    for key, child_schema in schema.get("required", {}).items():
        if key not in value:
            errors.append(f"missing required key {key}")
        else:
            errors.extend(f"{key}: {error}" for error in match_protocol_payload(child_schema, value[key]))
    for key, child_schema in schema.get("optional", {}).items():
        if key in value:
            errors.extend(f"{key}: {error}" for error in match_protocol_payload(child_schema, value[key]))
    return errors


def _entry_key(entry: dict[str, Any]) -> str:
    return f"{entry['channel']} {entry['direction']} {entry['name']}"


@dataclass
class FixtureLedger:
    expected: list[dict[str, Any]]
    counts: dict[str, int] = field(default_factory=dict)
    unexpected: list[str] = field(default_factory=list)
    states: list[tuple[list[int], int]] = field(init=False)

    def __post_init__(self) -> None:
        self.states = [([0] * len(self.expected), 0)]

    def record(self, *, channel: str, direction: str, name: str) -> None:
        entry = {"channel": channel, "direction": direction, "name": name}
        key = _entry_key(entry)
        matching_indices = [index for index, item in enumerate(self.expected) if _entry_key(item) == key]
        if not matching_indices:
            self.unexpected.append(key)
            return
        self.counts[key] = self.counts.get(key, 0) + 1
        next_states: dict[tuple[int, tuple[int, ...]], tuple[list[int], int]] = {}
        has_remaining_capacity = False
        for expectation_counts, highest_order in self.states:
            for index in matching_indices:
                expectation = self.expected[index]
                if expectation_counts[index] >= int(expectation["max"]):
                    continue
                has_remaining_capacity = True
                order = int(expectation["order"])
                if order < highest_order:
                    continue
                next_counts = list(expectation_counts)
                next_counts[index] += 1
                next_order = max(highest_order, order)
                next_states[(next_order, tuple(next_counts))] = (next_counts, next_order)
        if not next_states:
            if has_remaining_capacity:
                self.unexpected.append(f"{key} out of order")
                return
            allowed_max = sum(int(self.expected[index]["max"]) for index in matching_indices)
            self.unexpected.append(f"{key} exceeded max {allowed_max}")
            return
        self.states = list(next_states.values())

    def result(self) -> dict[str, Any]:
        def deficit(state: tuple[list[int], int]) -> int:
            expectation_counts, _ = state
            return sum(
                max(0, int(item["min"]) - expectation_counts[index])
                for index, item in enumerate(self.expected)
            )

        expectation_counts, _ = min(self.states, key=deficit)
        missing = [
            f"{_entry_key(item)} expected {item['min']}..{item['max']}"
            for index, item in enumerate(self.expected)
            if expectation_counts[index] < int(item["min"])
        ]
        return {
            "ok": not missing and not self.unexpected,
            "missing": missing,
            "unexpected": list(self.unexpected),
            "counts": dict(self.counts),
        }


@dataclass
class E2EState:
    token: str
    artifact_dir: Path
    backend_token: str = ""
    trusted_socket_origin: str = "yuizaki-app://renderer"
    fixture_origin: str = ""
    case_id: str | None = None
    ledger: FixtureLedger | None = None
    ping_count: int = 0
    online: bool = True
    socket_connect_count: int = 0
    socket_disconnect_count: int = 0
    agent_chat_count: int = 0
    pending_permissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_doc: dict[str, Any] | None = None
    socket_server: Any = None
    connected_sid: str = ""
    accepted_socket_token_hash: str = ""
    accepted_socket_origin: str = ""
    pending_proactive_event: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    def start_case(self, case_id: str) -> None:
        case = MANIFEST["cases"].get(case_id)
        if case is None:
            raise ValueError(f"unsupported E2E case: {case_id}")
        self.case_id = case_id
        self.ledger = FixtureLedger(expected=list(case["interactions"]))
        for entry in self.entries:
            self.ledger.record(**entry)

    def record(self, channel: str, direction: str, name: str) -> None:
        self.entries.append({"channel": channel, "direction": direction, "name": name})
        if self.ledger is not None:
            self.ledger.record(channel=channel, direction=direction, name=name)
        self.persist_log()

    def render_log(self) -> str:
        return "\n".join(json.dumps(entry, sort_keys=True) for entry in self.entries)

    def persist_log(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / "fixture-ledger.jsonl"
        path.write_text(self.render_log(), encoding="utf-8")
        return path

    def persist_security_audit(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / "fixture-security.json"
        path.write_text(json.dumps({
            "backend_token_hash": hashlib.sha256(self.backend_token.encode("utf-8")).hexdigest(),
            "trusted_socket_origin": self.trusted_socket_origin,
            "accepted_socket_token_hash": self.accepted_socket_token_hash,
            "accepted_socket_origin": self.accepted_socket_origin,
        }, sort_keys=True), encoding="utf-8")
        return path


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "testclient"}


def _authorize(request: Request, state: E2EState) -> JSONResponse | None:
    supplied = request.headers.get(TOKEN_HEADER, "")
    if not supplied:
        return JSONResponse({"error": "e2e_token_required"}, status_code=401)
    if not hmac.compare_digest(supplied, state.token) or not _is_loopback(request):
        return JSONResponse({"error": "e2e_control_forbidden"}, status_code=403)
    return None


def create_app(state: E2EState) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["yuizaki-app://renderer"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "x-trace-id", "x-yuizaki-backend-token"],
    )

    @app.middleware("http")
    async def backend_identity(request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path == "/api/ping"
            or path == "/audio.wav"
            or path == "/__e2e__"
            or path.startswith("/__e2e__/")
        ):
            return await call_next(request)
        allowed, message = verify_backend_api_authorization(
            request.headers.get("authorization"),
            state.backend_token,
            request.headers.get("x-yuizaki-backend-token"),
            client_host=request.client.host if request.client else None,
        )
        if not allowed:
            return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
        return await call_next(request)

    @app.get("/audio.wav")
    async def audio_asset(request: Request) -> Response:
        state.record("http", "renderer->fixture", "GET /audio.wav")
        if (
            state.case_id != "E2E-02"
            or not _is_loopback(request)
            or set(request.query_params) != {"token"}
            or not hmac.compare_digest(request.query_params.get("token", ""), state.token)
        ):
            return JSONResponse({"error": "e2e_audio_forbidden"}, status_code=403)
        return Response(
            content=SILENT_WAV_BYTES,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/ping")
    async def ping() -> JSONResponse:
        state.ping_count += 1
        if state.case_id is None:
            state.record("http", "supervisor->fixture", "GET /api/ping")
        elif state.ping_count == 2:
            state.record("http", "main->fixture", "GET /api/ping")
        else:
            state.record("http", "renderer->fixture", "GET /api/ping")
        if not state.online:
            return JSONResponse({"detail": "backend_unavailable"}, status_code=503)
        return JSONResponse({"ok": True})

    @app.post("/__e2e__/case/start")
    async def case_start(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        case_id = str(body.get("case_id", ""))
        try:
            state.start_case(case_id)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        state.record("http", "supervisor->fixture", "POST /__e2e__/case/start")
        return JSONResponse({"status": "ready", "case_id": case_id})

    @app.post("/__e2e__/case/assert")
    async def case_assert(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        if body.get("case_id") != state.case_id or state.ledger is None:
            return JSONResponse({"error": "e2e_case_mismatch"}, status_code=409)
        state.record("http", "main->fixture", "POST /__e2e__/case/assert")
        if state.case_id == "E2E-06" and (state.socket_connect_count != 2 or state.socket_disconnect_count != 2):
            state.ledger.unexpected.append(
                f"transport expected connect=2 disconnect=2, received connect={state.socket_connect_count} disconnect={state.socket_disconnect_count}"
            )
        result = state.ledger.result()
        result["transport"] = {
            "connect_count": state.socket_connect_count,
            "disconnect_count": state.socket_disconnect_count,
        }
        state.persist_log()
        return JSONResponse(result, status_code=200 if result["ok"] else 409)

    @app.post("/__e2e__/case/wait-disconnect")
    async def wait_disconnect(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        if body.get("case_id") != state.case_id:
            return JSONResponse({"error": "e2e_case_mismatch"}, status_code=409)
        deadline = asyncio.get_running_loop().time() + 5.0
        expected_count = 2 if state.case_id == "E2E-06" else 1
        while state.socket_disconnect_count < expected_count and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.025)
        if state.socket_disconnect_count < expected_count:
            return JSONResponse({"error": "e2e_disconnect_timeout"}, status_code=408)
        return JSONResponse({"status": "disconnected", "count": state.socket_disconnect_count})

    @app.post("/__e2e__/backend-mode")
    async def backend_mode(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        mode = body.get("mode")
        if state.case_id != "E2E-06" or set(body) != {"case_id", "mode"} or body.get("case_id") != "E2E-06" or mode not in {"online", "unavailable"}:
            return JSONResponse({"error": "invalid_backend_mode"}, status_code=422)
        state.record("http", "main->fixture", "POST /__e2e__/backend-mode")
        deadline = asyncio.get_running_loop().time() + 5.0
        if mode == "unavailable":
            while not state.connected_sid and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.025)
            if not state.connected_sid:
                return JSONResponse({"error": "e2e_initial_connect_timeout"}, status_code=408)
            state.online = False
        else:
            state.online = True
        if mode == "unavailable" and state.socket_server is not None:
            engine_sid = state.socket_server.manager.eio_sid_from_sid(state.connected_sid, "/")
            if engine_sid:
                engine_socket = state.socket_server.eio.sockets.get(engine_sid)
                if engine_socket is not None:
                    await engine_socket.close(wait=False, abort=True, reason=state.socket_server.eio.reason.TRANSPORT_ERROR)
                    await engine_socket.queue.put(None)
                    state.socket_server.eio.sockets.pop(engine_sid, None)
            while state.socket_disconnect_count < 1 and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.025)
        if mode == "online":
            while state.socket_connect_count < 2 and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.025)
            if state.socket_connect_count < 2:
                return JSONResponse({"error": "e2e_reconnect_timeout"}, status_code=408)
        return JSONResponse({"status": "ok", "mode": mode})

    @app.post("/__e2e__/proactive-event")
    async def proactive_event(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        event_id = body.get("event_id")
        if (
            state.case_id != "E2E-05"
            or set(body) != {"case_id", "event_id", "eligible", "interruptible"}
            or body.get("case_id") != "E2E-05"
            or event_id not in {"A", "B", "C"}
            or body.get("eligible") is not True
            or body.get("interruptible") is not True
        ):
            return JSONResponse({"error": "invalid_proactive_event"}, status_code=422)
        state.pending_proactive_event = str(event_id)
        state.record("http", "main->fixture", "POST /__e2e__/proactive-event")
        return JSONResponse({"status": "scheduled", "event_id": event_id})

    @app.post("/__e2e__/voice-sequence")
    async def voice_sequence(request: Request) -> JSONResponse:
        rejected = _authorize(request, state)
        if rejected is not None:
            return rejected
        body = await request.json()
        required = {"case_id", "session_id", "request_id", "partial_text", "final_text", "audio_chunks"}
        if (
            body.get("case_id") != "E2E-02"
            or state.case_id != "E2E-02"
            or set(body) != required
            or not state.connected_sid
            or state.socket_server is None
            or not 1 <= int(body.get("audio_chunks", 0)) <= 3
        ):
            return JSONResponse({"error": "e2e_case_mismatch"}, status_code=409)
        state.record("http", "main->fixture", "POST /__e2e__/voice-sequence")
        speech_start = {"session_id": body["session_id"], "confirmed_ms": 120}
        partial = {"session_id": body["session_id"], "text": body["partial_text"], "confidence": 0.82, "lang": "zh-CN"}
        final = {"session_id": body["session_id"], "text": body["final_text"], "confidence": 0.97, "lang": "zh-CN"}
        for name, payload in [
            ("asr:speech-start", speech_start),
            ("asr:partial", partial),
            ("asr:final", final),
        ]:
            state.record("socket", "fixture->renderer", name)
            await state.socket_server.emit(name, payload, to=state.connected_sid)
        return JSONResponse({"status": "scheduled", "sequence_id": "voice-sequence-1"})

    @app.get("/api/settings/")
    async def settings() -> dict[str, Any]:
        state.record("http", "renderer->fixture", "GET /api/settings/")
        return {"llm": {}, "tts": {}, "asr": {}, "svc": {}, "summary": {}, "system": {}}

    @app.get("/api/workspaces")
    async def workspaces() -> dict[str, Any]:
        state.record("http", "renderer->fixture", "GET /api/workspaces")
        return {"workspaces": [{"id": "default", "name": "E2E", "created_at": None, "updated_at": None}]}

    @app.get("/api/companions")
    async def companions() -> dict[str, Any]:
        state.record("http", "renderer->fixture", "GET /api/companions")
        return {"companions": [{"id": "default", "name": "E2E Companion", "created_at": None, "updated_at": None}]}

    @app.get("/api/companions/default")
    async def companion_detail() -> dict[str, Any]:
        state.record("http", "renderer->fixture", "GET /api/companions/default")
        return {
            "id": "default",
            "name": "E2E Companion",
            "emotion_state": "neutral",
            "energy_state": 0.8,
            "interruptibility_state": 0.8,
            "created_at": None,
            "updated_at": None,
        }

    @app.post("/api/system/active-workspace")
    async def active_workspace(request: Request) -> dict[str, Any]:
        body = await request.json()
        state.record("http", "renderer->fixture", "POST /api/system/active-workspace")
        return {"ok": True, "workspace_id": body.get("workspace_id", "default")}

    @app.get("/api/sessions")
    async def sessions(scope: str = "all") -> dict[str, Any]:
        state.record("http", "renderer->fixture", f"GET /api/sessions?scope={scope}")
        return {"sessions": []}

    @app.get("/api/system/companion-runtime")
    async def companion_runtime(limit: int = 8) -> JSONResponse:
        state.record("http", "renderer->fixture", f"GET /api/system/companion-runtime?limit={limit}")
        if not state.online:
            return JSONResponse({"detail": "backend_unavailable"}, status_code=503)
        event_id = state.pending_proactive_event
        state.pending_proactive_event = None
        behavior_events = []
        if state.case_id == "E2E-05" and event_id:
            behavior_events = [{
                "tick": {"A": 1, "B": 2, "C": 3}[event_id],
                "at": {"A": "2026-08-04T12:01:00Z", "B": "2026-08-04T12:02:00Z", "C": "2026-08-04T12:03:00Z"}[event_id],
                "type": "proactive_e2e",
                "message": f"E2E proactive {event_id}",
                "motion_group": "Tap@Body",
                "proactive_state": {"can_proactively_reach_out": True, "trigger_reason": f"fixture-{event_id}"},
            }]
        return JSONResponse({
            "active_workspace_id": "default",
            "active_companion": None,
            "heartbeat": {"behavior_events": behavior_events},
            "companion_state": {"interruptibility": 0.8},
            "memory_state": {},
        })

    @app.get("/memory/docs")
    async def memory_docs(scope: str = "", workspace_id: str = "") -> JSONResponse:
        state.record("http", "renderer->fixture", f"GET /memory/docs?scope={scope}&workspace_id={workspace_id}")
        if state.case_id != "E2E-04" or scope != "workspace" or workspace_id != "default":
            return JSONResponse({"error": "invalid_memory_scope"}, status_code=422)
        return JSONResponse({"docs": [state.memory_doc] if state.memory_doc is not None else []})

    @app.post("/memory/docs")
    async def create_memory_doc(request: Request) -> JSONResponse:
        body = await request.json()
        state.record("http", "renderer->fixture", "POST /memory/docs")
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        if (
            state.case_id != "E2E-04"
            or not isinstance(body.get("text"), str)
            or body.get("scope") != "workspace"
            or body.get("workspace_id") != "default"
            or "expires_at" not in metadata
        ):
            return JSONResponse({"error": "invalid_memory_create"}, status_code=422)
        doc_id = "memory-e2e-1"
        state.memory_doc = {
            "id": doc_id,
            "text": body["text"],
            "metadata": {
                **metadata,
                "scope": "workspace",
                "workspace_id": "default",
                "updated_at": "2026-08-04T12:00:00Z",
                "audit": [{"action": "create", "at": "2026-08-04T12:00:00Z", "reason": "e2e_create"}],
            },
        }
        return JSONResponse({"status": "ok", "id": doc_id})

    @app.put("/memory/docs/{doc_id}")
    async def update_memory_doc(doc_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        state.record("http", "renderer->fixture", f"PUT /memory/docs/{doc_id}")
        if (
            state.case_id != "E2E-04"
            or state.memory_doc is None
            or doc_id != state.memory_doc["id"]
            or not isinstance(body.get("text"), str)
            or not isinstance(body.get("edit_reason"), str)
            or not body["edit_reason"]
        ):
            return JSONResponse({"error": "invalid_memory_update"}, status_code=422)
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        state.memory_doc = {
            "id": doc_id,
            "text": body["text"],
            "metadata": {
                **state.memory_doc["metadata"],
                **metadata,
                "layer": body.get("layer", metadata.get("layer", "semantic")),
                "importance": body.get("importance", metadata.get("importance", 0.8)),
                "confidence": body.get("confidence", metadata.get("confidence", 0.9)),
                "updated_at": "2026-08-04T12:01:00Z",
                "audit": [
                    *state.memory_doc["metadata"].get("audit", []),
                    {"action": "update", "at": "2026-08-04T12:01:00Z", "reason": body["edit_reason"]},
                ],
            },
        }
        return JSONResponse({
            "status": "updated",
            "id": doc_id,
            "layer": state.memory_doc["metadata"]["layer"],
            "scope": "workspace",
            "importance": state.memory_doc["metadata"]["importance"],
        })

    @app.get("/api/memory/pipeline/query")
    async def query_memory_pipeline(request: Request, query: str, top_k: int, workspace_id: str) -> JSONResponse:
        state.record(
            "http",
            "renderer->fixture",
            f"GET /api/memory/pipeline/query?query={query}&top_k={top_k}&workspace_id={workspace_id}",
        )
        if (
            state.case_id != "E2E-04"
            or workspace_id != "default"
            or set(request.query_params.keys()) != {"query", "top_k", "workspace_id"}
        ):
            return JSONResponse({"error": "invalid_memory_query"}, status_code=422)
        results = [] if state.memory_doc is None else [{
            "id": state.memory_doc["id"],
            "text": state.memory_doc["text"],
            "score": 0.99,
            "metadata": state.memory_doc["metadata"],
        }]
        return JSONResponse({
            "query": query,
            "results": results,
            "trace": {
                "query": query,
                "scope": "workspace",
                "workspace_id": "default",
                "layers": ["semantic"],
                "recall_count": len(results),
                "selected_ids": [item["id"] for item in results],
                "candidate_count": len(results),
                "candidate_limit": top_k,
                "filtered_out_count": 0,
                "filter_reasons": {},
                "backend_filter_downpushed": True,
            },
        })

    @app.post("/memory/maintenance/preview")
    async def preview_memory_maintenance(request: Request) -> JSONResponse:
        body = await request.json()
        state.record("http", "renderer->fixture", "POST /memory/maintenance/preview")
        expected_keys = {
            "scope", "workspace_id", "working_retention_days", "low_quality_threshold",
            "include_stale_working", "include_low_quality", "include_exact_duplicates",
        }
        if (
            state.case_id != "E2E-04"
            or set(body) != expected_keys
            or body.get("scope") != "workspace"
            or body.get("workspace_id") != "default"
        ):
            return JSONResponse({"error": "invalid_memory_preview"}, status_code=422)
        count = 1 if state.memory_doc is not None else 0
        return JSONResponse({
            "status": "preview",
            "preview_token": "memory-preview-1",
            "policy": body,
            "summary": {"scanned_count": count, "active_count": count, "delete_count": 0},
            "candidates": [],
        })

    @app.delete("/memory/docs/{doc_id}")
    async def delete_memory_doc(doc_id: str) -> JSONResponse:
        state.record("http", "renderer->fixture", f"DELETE /memory/docs/{doc_id}")
        if state.case_id != "E2E-04" or state.memory_doc is None or doc_id != state.memory_doc["id"]:
            return JSONResponse({"error": "invalid_memory_delete"}, status_code=422)
        state.memory_doc = None
        return JSONResponse({"status": "deleted", "id": doc_id, "storage": {"deleted": 1}})

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        state.record("http", "renderer->fixture", "POST /v1/chat/completions")
        receipt = {
            "version": 1,
            "request_id": f"rest-{len(state.entries)}",
            "source": "fixture-rest",
            "reply": "fail closed",
            "actions": [{"type": "tool_trace", "payload": {"success": False, "side_effects": 0}}],
        }
        if body.get("stream"):
            async def stream():
                yield 'data: {"choices":[{"delta":{"content":"fail closed"}}]}\n\n'
                yield f"data: {json.dumps({'choices': [], 'action_envelope': receipt})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(stream(), media_type="text/event-stream")
        return JSONResponse({
            "choices": [{"message": {"role": "assistant", "content": "fail closed"}}],
            "action_envelope": receipt,
        })

    @app.get("/api/readiness")
    async def readiness() -> dict[str, Any]:
        state.record("http", "renderer->fixture", "GET /api/readiness")
        return {"ready": True, "checks": {"llm": {"ready": True, "message": "fixture"}}}

    @app.patch("/api/workspaces/default")
    async def patch_workspace(request: Request) -> dict[str, Any]:
        body = await request.json()
        state.record("http", "renderer->fixture", "PATCH /api/workspaces/default")
        return {"id": "default", "name": body.get("name", "E2E Workspace"), "created_at": None, "updated_at": None}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unhandled(request: Request, path: str) -> JSONResponse:
        state.record("http", "renderer->fixture", f"{request.method} /{path}")
        return JSONResponse({"error": "e2e_unhandled_request"}, status_code=404)

    return app


def _socket_origin(environ: dict[str, Any]) -> str:
    direct = str(environ.get("HTTP_ORIGIN", "")).strip()
    if direct:
        return direct
    scope = environ.get("asgi.scope")
    if not isinstance(scope, dict):
        return ""
    for key, value in scope.get("headers", []):
        if bytes(key).lower() == b"origin":
            return bytes(value).decode("latin-1").strip()
    return ""


def authorize_socket_connection(
    state: E2EState,
    environ: dict[str, Any],
    auth: dict[str, Any] | None,
) -> bool:
    supplied = str(auth.get("token", "")) if isinstance(auth, dict) else ""
    origin = _socket_origin(environ)
    return bool(
        supplied
        and state.backend_token
        and hmac.compare_digest(supplied, state.backend_token)
        and hmac.compare_digest(origin, state.trusted_socket_origin)
    )


def create_asgi_app(state: E2EState) -> socketio.ASGIApp:
    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[state.trusted_socket_origin])
    state.socket_server = sio
    http_app = create_app(state)

    @sio.event
    async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None) -> bool:
        if not authorize_socket_connection(state, environ, auth):
            return False
        if not state.online:
            return False
        state.socket_connect_count += 1
        state.connected_sid = sid
        state.accepted_socket_token_hash = hashlib.sha256(state.backend_token.encode("utf-8")).hexdigest()
        state.accepted_socket_origin = _socket_origin(environ)
        state.persist_security_audit()
        state.record("socket", "renderer->fixture", "connect")
        return True

    @sio.event
    async def disconnect(sid: str, reason: str) -> None:
        del reason
        state.socket_disconnect_count += 1
        if state.connected_sid == sid:
            state.connected_sid = ""
        state.record("socket", "renderer->fixture", "disconnect")

    @sio.on("heartbeat")
    async def heartbeat(sid: str, payload: dict[str, Any]) -> None:
        state.record("socket", "renderer->fixture", "heartbeat")
        await sio.emit("heartbeat", dict(payload), to=sid)
        state.record("socket", "fixture->renderer", "heartbeat")

    @sio.on("agent:chat")
    async def agent_chat(sid: str, payload: dict[str, Any]) -> None:
        errors = match_protocol_payload(MANIFEST["production_protocol"]["event_schemas"]["agent:chat"], payload)
        if errors:
            state.record("socket", "renderer->fixture", f"agent:chat invalid: {'; '.join(errors)}")
            return
        state.record("socket", "renderer->fixture", "agent:chat")
        state.agent_chat_count += 1
        session_id = payload["session_id"]
        state.record("socket", "fixture->renderer", "llm:delta")
        await sio.emit("llm:delta", {"token": "ok", "index": 0, "session_id": session_id}, to=sid)
        if state.case_id == "E2E-02":
            generation_id = f"e2e-generation-{state.agent_chat_count}"
            if not state.fixture_origin:
                raise RuntimeError("fixture origin is unavailable")
            chunk = {
                "session_id": session_id,
                "generation_id": generation_id,
                "sequence": 0,
                "is_final": False,
                "audio_url": f"{state.fixture_origin}/audio.wav?token={state.token}",
                "text": "fixture voice response",
            }
            state.record("socket", "fixture->renderer", "tts:chunk")
            await sio.emit("tts:chunk", chunk, to=sid)
            if state.agent_chat_count == 2:
                return
            state.record("socket", "fixture->renderer", "llm:final")
            await sio.emit("llm:final", {
                "text": "fixture voice response",
                "session_id": session_id,
                "total_tokens": 1,
                "finish_reason": "stop",
            }, to=sid)
            state.record("socket", "fixture->renderer", "tts:done")
            await sio.emit("tts:done", {
                "session_id": session_id,
                "generation_id": generation_id,
                "sequence": 1,
                "is_final": True,
                "complete": True,
            }, to=sid)
            return
        if state.case_id == "E2E-03":
            permission_id = f"permission-{state.agent_chat_count}"
            state.pending_permissions[permission_id] = {
                "sid": sid,
                "session_id": session_id,
                "request_id": payload.get("request_id", ""),
            }
            request = {
                "request_id": permission_id,
                "tool_name": "fixture.write",
                "capability_id": "fixture.write",
                "capability_type": "tool",
                "capability_kind": "local",
                "permission_scope": "once",
                "risk_level": "high",
                "reason": "E2E permission receipt",
                "args": {"target": "synthetic.txt"},
            }
            state.record("socket", "fixture->renderer", "permission:request")
            await sio.emit("permission:request", request, to=sid)
            return
        if state.case_id == "E2E-01" and state.agent_chat_count == 2:
            return
        state.record("socket", "fixture->renderer", "llm:final")
        await sio.emit("llm:final", {"text": "fixture response", "session_id": session_id, "total_tokens": 1, "finish_reason": "stop"}, to=sid)

    @sio.on("interrupt")
    async def interrupt(sid: str, payload: dict[str, Any]) -> None:
        state.record("socket", "renderer->fixture", "interrupt")
        response = {
            "request_id": payload.get("request_id", ""),
            "session_id": payload.get("session_id", ""),
            "source": payload.get("source", "manual"),
            "generation_id": "e2e-generation-2",
            "hit_active_generation": True,
            "server_processing_ms": 0,
        }
        state.record("socket", "fixture->renderer", "interrupt:ack")
        await sio.emit("interrupt:ack", response, to=sid)

    @sio.on("system:client-timing")
    async def client_timing(sid: str, payload: dict[str, Any]) -> None:
        del sid
        stage = payload.get("stage", "unknown")
        state.record("socket", "renderer->fixture", f"system:client-timing:{stage}")

    @sio.on("permission:response")
    async def permission_response(sid: str, payload: dict[str, Any]) -> None:
        state.record("socket", "renderer->fixture", "permission:response")
        request_id = str(payload.get("request_id", ""))
        pending = state.pending_permissions.pop(request_id, None)
        if pending is None or pending["sid"] != sid:
            return
        allowed = payload.get("allowed") is True
        text = "permission allowed receipt" if allowed else "permission denied receipt"
        state.record("socket", "fixture->renderer", "llm:final")
        await sio.emit("llm:final", {
            "text": text,
            "session_id": pending["session_id"],
            "total_tokens": 1,
            "finish_reason": "stop",
        }, to=sid)
        envelope = {
            "version": 1,
            "request_id": pending["request_id"],
            "source": "fixture-permission",
            "reply": text,
            "actions": [{
                "type": "tool_trace",
                "payload": {"success": allowed, "side_effects": 1 if allowed else 0},
            }],
        }
        state.record("socket", "fixture->renderer", "agent:result")
        await sio.emit("agent:result", envelope, to=sid)

    @sio.on("screenshot:request")
    async def screenshot_request(sid: str, payload: dict[str, Any]) -> None:
        state.record("socket", "renderer->fixture", "screenshot:request")
        response = {
            "status": "ok",
            "mode": payload.get("mode", "observe"),
            "frame_id": payload.get("frame_id"),
            "received_at": int(asyncio.get_running_loop().time() * 1000),
            "analysis_status": "skipped",
            "analysis_reason": "fixture",
            "analysis_attempts": 0,
            "analysis_skipped": 1,
            "change_score": payload.get("change_score"),
            "capture_reason": payload.get("capture_reason"),
            "analysis_latency_ms": 0,
        }
        state.record("socket", "fixture->renderer", "screenshot:result")
        await sio.emit("screenshot:result", response, to=sid)

    return socketio.ASGIApp(sio, other_asgi_app=http_app, socketio_path="socket.io")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.host not in {"127.0.0.1", "::1"}:
        raise SystemExit("E2E fixture host must be loopback")
    backend_token = os.getenv("YUIZAKI_E2E_BACKEND_TOKEN", "").strip()
    trusted_socket_origin = os.getenv("YUIZAKI_E2E_SOCKET_ORIGIN", "").strip()
    if not backend_token:
        raise SystemExit("YUIZAKI_E2E_BACKEND_TOKEN is required")
    if trusted_socket_origin != "yuizaki-app://renderer":
        raise SystemExit("YUIZAKI_E2E_SOCKET_ORIGIN must be the trusted renderer origin")
    state = E2EState(
        token=args.token,
        artifact_dir=args.artifact_dir,
        backend_token=backend_token,
        trusted_socket_origin=trusted_socket_origin,
    )
    state.persist_security_audit()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(128)
    port = listener.getsockname()[1]
    state.fixture_origin = f"http://{args.host}:{port}"
    print(json.dumps({"type": "yuizaki-e2e-fixture", "port": port, "manifest_hash": MANIFEST_HASH}), flush=True)
    config = uvicorn.Config(create_asgi_app(state), host=args.host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(sockets=[listener]))


if __name__ == "__main__":
    main()

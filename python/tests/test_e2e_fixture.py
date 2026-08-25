from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from tests.fixtures.e2e_backend import (
    E2EState,
    FixtureLedger,
    MANIFEST_HASH,
    create_app,
    authorize_socket_connection,
    load_manifest,
    match_protocol_payload,
)


def test_fixture_ledger_supports_ordered_repeated_routes() -> None:
    repeated = {"channel": "http", "direction": "renderer->fixture", "name": "GET /memory/docs"}
    ledger = FixtureLedger(expected=[
        {**repeated, "min": 1, "max": 1, "order": 1},
        {"channel": "http", "direction": "renderer->fixture", "name": "PUT /memory/docs/id", "min": 1, "max": 1, "order": 2},
        {**repeated, "min": 1, "max": 1, "order": 3},
    ])

    ledger.record(**repeated)
    ledger.record(channel="http", direction="renderer->fixture", name="PUT /memory/docs/id")
    ledger.record(**repeated)

    assert ledger.result()["ok"] is True
    assert ledger.result()["counts"]["http renderer->fixture GET /memory/docs"] == 2


def test_fixture_ledger_rejects_reversed_socket_sequences() -> None:
    scenarios = [
        (
            [
                {"channel": "socket", "direction": "fixture->renderer", "name": "llm:delta", "min": 1, "max": 2, "order": 1},
                {"channel": "socket", "direction": "fixture->renderer", "name": "llm:final", "min": 1, "max": 1, "order": 2},
            ],
            {"channel": "socket", "direction": "fixture->renderer", "name": "llm:final"},
            {"channel": "socket", "direction": "fixture->renderer", "name": "llm:delta"},
        ),
        (
            [
                {"channel": "socket", "direction": "fixture->renderer", "name": "permission:request", "min": 1, "max": 1, "order": 1},
                {"channel": "socket", "direction": "renderer->fixture", "name": "permission:response", "min": 1, "max": 1, "order": 2},
            ],
            {"channel": "socket", "direction": "renderer->fixture", "name": "permission:response"},
            {"channel": "socket", "direction": "fixture->renderer", "name": "permission:request"},
        ),
        (
            [
                {"channel": "socket", "direction": "renderer->fixture", "name": "heartbeat", "min": 1, "max": 1, "order": 1},
                {"channel": "socket", "direction": "fixture->renderer", "name": "heartbeat", "min": 1, "max": 1, "order": 2},
            ],
            {"channel": "socket", "direction": "fixture->renderer", "name": "heartbeat"},
            {"channel": "socket", "direction": "renderer->fixture", "name": "heartbeat"},
        ),
    ]

    for expected, later, earlier in scenarios:
        ledger = FixtureLedger(expected=expected)
        ledger.record(**later)
        ledger.record(**earlier)
        assert f"{_entry_key_for_test(earlier)} out of order" in ledger.result()["unexpected"]


def test_fixture_ledger_allows_same_order_and_disambiguates_optional_duplicates() -> None:
    first = {"channel": "socket", "direction": "fixture->renderer", "name": "first"}
    second = {"channel": "socket", "direction": "fixture->renderer", "name": "second"}
    duplicate = {"channel": "socket", "direction": "fixture->renderer", "name": "duplicate"}
    middle = {"channel": "socket", "direction": "fixture->renderer", "name": "middle"}
    ledger = FixtureLedger(expected=[
        {**first, "min": 1, "max": 1, "order": 1},
        {**second, "min": 1, "max": 1, "order": 1},
        {**duplicate, "min": 0, "max": 1, "order": 2},
        {**middle, "min": 1, "max": 1, "order": 3},
        {**duplicate, "min": 1, "max": 1, "order": 4},
    ])

    ledger.record(**second)
    ledger.record(**first)
    ledger.record(**duplicate)
    ledger.record(**middle)
    ledger.record(**duplicate)

    assert ledger.result()["ok"] is True


def _entry_key_for_test(entry: dict[str, str]) -> str:
    return f"{entry['channel']} {entry['direction']} {entry['name']}"


def test_fixture_loads_same_four_part_manifest_and_hash() -> None:
    manifest = load_manifest()

    assert list(manifest) == [
        "production_protocol",
        "fixture_variants",
        "e2e_controls",
        "cases",
    ]
    assert MANIFEST_HASH == "11d3256146f8e31a18d5f538eff800201db5832461522355b6d89c32256ba3ca"


def test_fixture_matcher_keeps_case_variant_below_production_authority() -> None:
    manifest = load_manifest()
    schema = manifest["production_protocol"]["event_schemas"]["tts:done"]

    assert match_protocol_payload(
        schema,
        {
            "session_id": "s1",
            "generation_id": "g1",
            "turn_id": "t1",
            "request_id": "r1",
            "interruption_epoch": 0,
            "version": 1,
            "sequence": 1,
            "is_final": True,
            "complete": True,
        },
    ) == []
    assert match_protocol_payload(
        schema,
        {
            "session_id": "s1",
            "generation_id": "g1",
            "turn_id": "t1",
            "request_id": "r1",
            "interruption_epoch": 0,
            "version": 1,
            "sequence": 1,
            "is_final": True,
            "audio_url": "http://127.0.0.1/audio.wav",
            "text": "done",
        },
    ) == []
    assert manifest["fixture_variants"]["E2E-02"]["tts_done_variant"] == "complete-marker"


def test_e2e_audio_asset_requires_loopback_run_token(tmp_path: Path) -> None:
    state = E2EState(
        token="secret-token",
        artifact_dir=tmp_path,
        fixture_origin="http://127.0.0.1:43210",
    )
    state.start_case("E2E-02")
    client = TestClient(create_app(state))

    assert client.get("/audio.wav").status_code == 403
    assert client.get("/audio.wav?token=wrong").status_code == 403
    response = client.get("/audio.wav?token=secret-token")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert "secret-token" not in state.render_log()
    assert state.entries[-1] == {
        "channel": "http",
        "direction": "renderer->fixture",
        "name": "GET /audio.wav",
    }


def test_loopback_controls_require_token_and_unexpected_requests_fail_assertion(tmp_path: Path) -> None:
    state = E2EState(token="secret-token", artifact_dir=tmp_path, backend_token="backend-token")
    client = TestClient(create_app(state))

    assert client.post("/__e2e__/case/start", json={"case_id": "E2E-08"}).status_code == 401
    assert client.post(
        "/__e2e__/case/start",
        headers={"X-Yuizaki-E2E-Token": "wrong"},
        json={"case_id": "E2E-08"},
    ).status_code == 403
    assert client.get("/api/ping").json() == {"ok": True}
    assert client.post(
        "/__e2e__/case/start",
        headers={"X-Yuizaki-E2E-Token": "secret-token"},
        json={"case_id": "E2E-08"},
    ).json() == {"status": "ready", "case_id": "E2E-08"}

    assert client.get("/api/unlisted", headers={"Authorization": "Bearer backend-token"}).status_code == 404
    result = client.post(
        "/__e2e__/case/assert",
        headers={"X-Yuizaki-E2E-Token": "secret-token"},
        json={"case_id": "E2E-08"},
    )
    assert result.status_code == 409
    assert any("GET /api/unlisted" in item for item in result.json()["unexpected"])
    assert "secret-token" not in state.render_log()


def test_fixture_production_routes_require_consistent_backend_identity(tmp_path: Path) -> None:
    backend_token = "backend-secret-token"
    state = E2EState(token="run-control-token", artifact_dir=tmp_path, backend_token=backend_token)
    client = TestClient(create_app(state))

    assert client.get("/api/workspaces").status_code == 401
    assert client.get("/api/workspaces", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/workspaces", headers={"x-yuizaki-backend-token": "wrong"}).status_code == 401
    assert client.get(
        "/api/workspaces",
        headers={
            "Authorization": f"Bearer {backend_token}",
            "x-yuizaki-backend-token": "wrong",
        },
    ).status_code == 401
    assert client.get(
        "/api/workspaces",
        headers={
            "Authorization": "Bearer wrong",
            "x-yuizaki-backend-token": backend_token,
        },
    ).status_code == 401
    assert client.get(
        "/api/workspaces",
        headers={
            "Authorization": f"Bearer {backend_token}",
            "x-yuizaki-backend-token": backend_token,
        },
    ).status_code == 200

    assert client.get("/api/ping").status_code == 200
    assert client.get("/audio.wav").status_code == 403
    assert client.post(
        "/__e2e__/case/start",
        headers={"X-Yuizaki-E2E-Token": "run-control-token"},
        json={"case_id": "E2E-08"},
    ).status_code == 200
    assert backend_token not in state.render_log()


def test_ping_direction_uses_request_identity_instead_of_arrival_count(tmp_path: Path) -> None:
    state = E2EState(token="run-token", artifact_dir=tmp_path, backend_token="backend-token")
    client = TestClient(create_app(state))

    assert client.get("/api/ping").status_code == 200
    state.start_case("E2E-01")
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping", headers={"Origin": state.trusted_socket_origin}).status_code == 200
    assert client.get("/api/ping", headers={"Authorization": "Bearer backend-token"}).status_code == 200
    assert client.get("/api/ping", headers={"Origin": "https://untrusted.example"}).status_code == 200

    assert [entry["direction"] for entry in state.entries if entry["name"] == "GET /api/ping"] == [
        "supervisor->fixture",
        "main->fixture",
        "renderer->fixture",
        "renderer->fixture",
        "untrusted->fixture",
    ]


def test_onboarding_readiness_run_models_main_process_probe(tmp_path: Path) -> None:
    backend_token = "backend-token"
    state = E2EState(token="run-token", artifact_dir=tmp_path, backend_token=backend_token)
    state.start_case("E2E-01")
    client = TestClient(create_app(state))

    response = client.post(
        "/api/system/onboarding/readiness/run",
        headers={"x-yuizaki-backend-token": backend_token},
        json={},
    )

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["schemaVersion"] == 1
    assert snapshot["state"] == "completed"
    assert snapshot["readyForText"] is True
    assert {probe["id"] for probe in snapshot["probes"]} >= {
        "backend.service",
        "llm.provider",
        "llm.model_chat",
    }
    assert state.entries[-1] == {
        "channel": "http",
        "direction": "main->fixture",
        "name": "POST /api/system/onboarding/readiness/run",
    }


def test_socket_connect_requires_exact_backend_token_and_trusted_renderer_origin(tmp_path: Path) -> None:
    backend_token = "production-backend-secret"
    trusted_origin = "yuizaki-app://renderer"
    state = E2EState(
        token="e2e-proof-secret",
        artifact_dir=tmp_path,
        backend_token=backend_token,
        trusted_socket_origin=trusted_origin,
    )
    trusted_environ = {"HTTP_ORIGIN": trusted_origin}

    assert authorize_socket_connection(state, trusted_environ, None) is False
    assert authorize_socket_connection(state, trusted_environ, {"token": ""}) is False
    assert authorize_socket_connection(state, trusted_environ, {"token": "wrong"}) is False
    assert authorize_socket_connection(state, {"HTTP_ORIGIN": "http://127.0.0.1:38945"}, {"token": backend_token}) is False
    assert authorize_socket_connection(state, trusted_environ, {"token": backend_token}) is True
    assert authorize_socket_connection(
        state,
        {"asgi.scope": {"headers": [(b"origin", trusted_origin.encode("ascii"))]}},
        {"token": backend_token},
    ) is True

    state.persist_security_audit()
    artifact = (tmp_path / "fixture-security.json").read_text(encoding="utf-8")
    assert backend_token not in artifact
    assert "e2e-proof-secret" not in artifact
    assert hashlib.sha256(backend_token.encode("utf-8")).hexdigest() in artifact

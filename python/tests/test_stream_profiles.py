from __future__ import annotations

from typing import Any

import pytest

from modules.system.stream_runtime import StreamRuntime
from routes.system_api import create_system_router


class FakeObs:
    configured = True

    def __init__(self, *, current: str = "Default", fail_verification: bool = False) -> None:
        self.current = current
        self.fail_verification = fail_verification
        self.calls: list[tuple[str, Any]] = []

    def get_profile_list(self) -> dict[str, Any]:
        self.calls.append(("list", None))
        return {"profiles": [{"profileName": "Default"}, {"profileName": "Vertical"}], "currentProfileName": self.current}

    def set_current_profile(self, profile_name: str) -> dict[str, Any]:
        self.calls.append(("set", profile_name))
        self.current = profile_name
        return {}

    def get_current_profile(self) -> dict[str, Any]:
        self.calls.append(("current", None))
        return {"currentProfileName": "Other" if self.fail_verification else self.current}


def test_obs_profiles_is_read_only_and_bounded() -> None:
    adapter = FakeObs()
    stream = StreamRuntime(obs_adapter=adapter)

    result = stream.obs_profiles()

    assert result == {
        "schemaVersion": "1.0",
        "ok": True,
        "profiles": [{"profileName": "Default"}, {"profileName": "Vertical"}],
        "currentProfileName": "Default",
        "externalSideEffects": False,
    }
    assert adapter.calls == [("list", None)]
    assert stream.actions()["actions"] == []


def test_profile_switch_requires_preview_and_verifies_after_switch() -> None:
    adapter = FakeObs()
    stream = StreamRuntime(obs_adapter=adapter)
    preview = stream.preview({"action": "stream.profile_switch", "params": {"profileName": "Vertical"}})

    stream.set_takeover(False)
    result = stream.execute({
        "requestId": preview["preview"]["requestId"],
        "action": "stream.profile_switch",
        "params": {"profileName": "Vertical"},
        "confirmed": True,
    })

    assert result["ok"] is True
    assert result["outcome"] == "known_success"
    assert result["verificationStatus"] == "provider_acknowledged"
    assert adapter.calls == [("set", "Vertical"), ("current", None)]
    assert stream.actions()["actions"][0]["action"] == "stream.profile_switch"


def test_profile_switch_verification_mismatch_is_unknown_effect() -> None:
    stream = StreamRuntime(obs_adapter=FakeObs(fail_verification=True))
    preview = stream.preview({"action": "stream.profile_switch", "params": {"profileName": "Vertical"}})
    stream.set_takeover(False)

    with pytest.raises(RuntimeError, match="unknown_effect"):
        stream.execute({
            "requestId": preview["preview"]["requestId"],
            "action": "stream.profile_switch",
            "params": {"profileName": "Vertical"},
            "confirmed": True,
        })

    assert stream.actions()["actions"][0]["status"] == "unknown_effect"


def test_obs_profiles_route_is_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_obs_profiles_handler=lambda: {"ok": True, "profiles": []},
    )

    assert "/api/system/stream/obs/profiles" in {route.path for route in router.routes}

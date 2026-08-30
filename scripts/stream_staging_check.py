"""Replay the local stream control chain without network or real providers.

The check exercises the same ``StreamRuntime`` preview/confirm/execute/verify
path used by the UI, but all OBS and Twitch state lives in deterministic in-
memory fakes.  It is a contract/staging check, not proof of real platform
connectivity or permission to publish.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modules.system.stream_platforms import InMemoryTwitchSubscriptionProvider
from modules.system.stream_runtime import StreamRuntime

SCHEMA_VERSION = "yuizaki.stream-staging-evaluation.v1"


class StagingObs:
    """Deterministic OBS adapter; it never opens a socket."""

    configured = True

    def __init__(self, *, mismatch_scene: bool = False) -> None:
        self.scene = "Starting"
        self.profile = "Default"
        self.output_active = False
        self.mismatch_scene = mismatch_scene
        self.calls: list[str] = []

    def get_scene_list(self) -> dict[str, Any]:
        self.calls.append("get_scene_list")
        return {"scenes": [{"sceneName": "Starting"}, {"sceneName": "Gameplay"}]}

    def get_profile_list(self) -> dict[str, Any]:
        self.calls.append("get_profile_list")
        return {"profiles": [{"profileName": "Default"}, {"profileName": "Vertical"}], "currentProfileName": self.profile}

    def get_current_profile(self) -> dict[str, Any]:
        self.calls.append("get_current_profile")
        return {"currentProfileName": self.profile}

    def set_current_profile(self, profile_name: str) -> dict[str, Any]:
        self.calls.append(f"set_current_profile:{profile_name}")
        self.profile = profile_name
        return {}

    def get_current_program_scene(self) -> dict[str, Any]:
        self.calls.append("get_current_program_scene")
        return {"currentProgramSceneName": "Other" if self.mismatch_scene else self.scene}

    def set_current_program_scene(self, scene_name: str) -> dict[str, Any]:
        self.calls.append(f"set_current_program_scene:{scene_name}")
        self.scene = scene_name
        return {}

    def get_stream_status(self) -> dict[str, Any]:
        self.calls.append("get_stream_status")
        return {"outputActive": self.output_active}

    def start_stream(self) -> dict[str, Any]:
        self.calls.append("start_stream")
        self.output_active = True
        return {}

    def stop_stream(self) -> dict[str, Any]:
        self.calls.append("stop_stream")
        self.output_active = False
        return {}


def _execute(runtime: StreamRuntime, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    # The harness models an explicit operator confirmation before execution.
    runtime.set_takeover(False)
    preview = runtime.preview({"action": action, "params": params or {}})
    result = runtime.execute({
        "requestId": preview["preview"]["requestId"],
        "action": action,
        "params": params or {},
        "confirmed": True,
    })
    return result


def _case(name: str, callback) -> dict[str, Any]:
    try:
        details = callback()
        return {"name": name, "passed": True, "details": details}
    except Exception as exc:  # noqa: BLE001 - report every scenario and keep the check bounded.
        return {"name": name, "passed": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def run_staging_checks() -> dict[str, Any]:
    def caption_local() -> dict[str, Any]:
        runtime = StreamRuntime()
        result = _execute(runtime, "stream.caption_draft", {"text": "欢迎来到直播间"})
        assert result["outcome"] == "known_success"
        assert result["externalSideEffects"] is False
        return {"outcome": result["outcome"], "audit": runtime.actions(5)["actions"]}

    def obs_success() -> dict[str, Any]:
        adapter = StagingObs()
        runtime = StreamRuntime(obs_adapter=adapter)
        result = _execute(runtime, "stream.scene_switch", {"sceneName": "Gameplay"})
        assert result["outcome"] == "known_success"
        assert result["verificationStatus"] == "provider_acknowledged"
        assert adapter.scene == "Gameplay"
        return {"outcome": result["outcome"], "providerCalls": len(adapter.calls)}

    def unknown_effect_is_terminal() -> dict[str, Any]:
        adapter = StagingObs(mismatch_scene=True)
        runtime = StreamRuntime(obs_adapter=adapter)
        runtime.set_takeover(False)
        preview = runtime.preview({"action": "stream.scene_switch", "params": {"sceneName": "Gameplay"}})
        payload = {
            "requestId": preview["preview"]["requestId"],
            "action": "stream.scene_switch",
            "params": {"sceneName": "Gameplay"},
            "confirmed": True,
        }
        try:
            runtime.execute(payload)
        except RuntimeError as exc:
            assert "unknown_effect" in str(exc)
        else:
            raise AssertionError("verification mismatch unexpectedly succeeded")
        assert runtime.actions(2)["actions"][0]["status"] == "unknown_effect"
        try:
            runtime.execute(payload)
        except ValueError as exc:
            assert "unknown or already used" in str(exc)
        else:
            raise AssertionError("unknown-effect ticket was replayable")
        return {"status": "unknown_effect", "replay": "blocked", "providerCalls": len(adapter.calls)}

    def takeover_blocks_provider() -> dict[str, Any]:
        adapter = StagingObs()
        runtime = StreamRuntime(obs_adapter=adapter)
        preview = runtime.preview({"action": "stream.broadcast_start", "params": {}})
        try:
            runtime.execute({
                "requestId": preview["preview"]["requestId"],
                "action": "stream.broadcast_start",
                "params": {},
                "confirmed": True,
            })
        except RuntimeError as exc:
            assert "human takeover" in str(exc)
        else:
            raise AssertionError("human takeover did not block execution")
        assert adapter.calls == []
        return {"blocked": True, "providerCalls": 0}

    def subscription_sync_is_local() -> dict[str, Any]:
        provider = InMemoryTwitchSubscriptionProvider(["channel.follow"])
        runtime = StreamRuntime(
            twitch_eventsub_secret="staging-secret",
            twitch_subscription_provider=provider,
        )
        runtime.configure_twitch_subscriptions({"subscriptions": ["channel.chat.message", "channel.follow"]})
        result = _execute(runtime, "stream.twitch_subscriptions_sync")
        assert result["outcome"] == "known_success"
        assert result["result"]["subscriptionPlan"]["status"] == "synced"
        assert result["externalSideEffects"] is True
        return {"outcome": result["outcome"], "provider": "in-memory-staging", "network": False}

    def audit_survives_restart() -> dict[str, Any]:
        with TemporaryDirectory(prefix="yuizaki-stream-staging-") as directory:
            actions_path = Path(directory) / "stream_actions.json"
            adapter = StagingObs()
            runtime = StreamRuntime(obs_adapter=adapter, actions_path=actions_path)
            result = _execute(runtime, "stream.broadcast_start")
            assert result["outcome"] == "known_success"
            restarted = StreamRuntime(actions_path=actions_path)
            actions = restarted.actions(5)["actions"]
            assert actions[0]["status"] == "known_success"
            assert all("params" not in item and "result" not in item for item in actions)
            return {"status": actions[0]["status"], "actionCount": len(actions)}

    scenarios = [
        _case("caption_local_only", caption_local),
        _case("obs_scene_switch_verified", obs_success),
        _case("unknown_effect_is_terminal", unknown_effect_is_terminal),
        _case("human_takeover_blocks_provider", takeover_blocks_provider),
        _case("twitch_subscription_sync_local_provider", subscription_sync_is_local),
        _case("action_audit_survives_restart", audit_survives_restart),
    ]
    passed = sum(item["passed"] is True for item in scenarios)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "networkAccess": False,
        "realProviders": False,
        "claim": "local_stream_contract_replay_only",
        "summary": {"passed": passed, "total": len(scenarios)},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_staging_checks()
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(args.output)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    print(payload)
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

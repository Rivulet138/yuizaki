from __future__ import annotations

from modules.system.release_readiness import (
    build_release_readiness_snapshot,
    evaluate_soak_report,
)


def _capabilities(*, desktop: str = "available") -> dict[str, object]:
    return {
        "host": {"system": "windows"},
        "platforms": [
            {
                "id": "windows",
                "host": True,
                "capabilities": {
                    "desktop": {"status": desktop},
                    "live2d_vrm": {"status": "available"},
                    "text_voice": {"status": "available"},
                },
            },
        ],
    }


def _soak_report(*, rss_end: int = 110, cpu_end: float = 20.0) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "durationSeconds": 86400,
        "samples": [
            {
                "timestampSeconds": 0,
                "rssBytes": 100,
                "openHandles": 100,
                "gpuBytes": 100,
                "cpuPct": 10.0,
            },
            {
                "timestampSeconds": 86400,
                "rssBytes": rss_end,
                "openHandles": 105,
                "gpuBytes": 110,
                "cpuPct": cpu_end,
            },
        ],
    }


def test_release_gate_is_fail_closed_without_target_attestation_or_soak() -> None:
    result = build_release_readiness_snapshot(
        capability_snapshot=_capabilities(),
        target_platform="windows",
    )

    assert result["status"] == "not_qualified"
    assert {reason["code"] for reason in result["reasons"]} >= {
        "platform_attestation_missing",
        "soak_report_missing",
    }
    assert result["claim"] == "must_not_be_used_as_release_qualification"


def test_release_gate_passes_only_with_matching_attestation_and_complete_soak() -> None:
    result = build_release_readiness_snapshot(
        capability_snapshot=_capabilities(),
        platform_qualification={
            "status": "qualified",
            "targetPlatform": "windows",
            "deviceId": "opaque-device-1",
        },
        soak_report=_soak_report(),
        target_platform="windows",
    )

    assert result["status"] == "qualified"
    assert result["claim"] == "product_release_gate_passed"
    assert result["evidence"]["platformAttestationSha256"]
    assert result["evidence"]["soakReportSha256"]
    assert result["soak"]["status"] == "pass"


def test_release_gate_rejects_capability_mismatch_attestation_mismatch_and_growth() -> None:
    capability_mismatch = build_release_readiness_snapshot(
        capability_snapshot=_capabilities(desktop="experimental"),
        platform_qualification={"status": "qualified", "targetPlatform": "windows"},
        soak_report=_soak_report(),
        target_platform="windows",
    )
    assert capability_mismatch["status"] == "not_qualified"
    assert any(reason["code"] == "platform_capability_unqualified" for reason in capability_mismatch["reasons"])

    attestation_mismatch = build_release_readiness_snapshot(
        capability_snapshot=_capabilities(),
        platform_qualification={"status": "qualified", "targetPlatform": "linux"},
        soak_report=_soak_report(),
        target_platform="windows",
    )
    assert attestation_mismatch["status"] == "not_qualified"
    assert any(reason["code"] == "platform_attestation_target_mismatch" for reason in attestation_mismatch["reasons"])

    growth_exceeded = evaluate_soak_report(_soak_report(rss_end=130))
    assert growth_exceeded["status"] == "not_qualified"
    assert growth_exceeded["reasons"][0]["code"] == "soak_growth_exceeded"


def test_soak_report_rejects_non_monotonic_or_mismatched_samples() -> None:
    report = _soak_report()
    report["samples"] = [report["samples"][1], report["samples"][0]]
    result = evaluate_soak_report(report)
    assert result["status"] == "not_qualified"
    assert result["reasons"][0]["code"] == "soak_timestamp_not_monotonic"

    mismatch = _soak_report()
    mismatch["durationSeconds"] = 90000
    result = evaluate_soak_report(mismatch)
    assert result["status"] == "not_qualified"
    assert result["reasons"][0]["code"] == "soak_duration_mismatch"

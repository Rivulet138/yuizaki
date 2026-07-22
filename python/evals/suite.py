"""Deterministic model-quality evaluation runner.

The runner evaluates captured results rather than invoking providers. This
keeps CI offline while preserving enough metadata to attribute a regression to
the fixture source and model/provider used to collect it.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .metrics import character_error_rate, embedding_recall_at_k, real_time_factor, tool_success_rate, token_error_rate


SCHEMA_VERSION = 1
DEFAULT_FIXTURE = Path(__file__).with_name("fixtures") / "smoke.json"
DEFAULT_THRESHOLDS = {
    "asr_wer_max": 0.20,
    "asr_cer_max": 0.20,
    "tts_rtf_max": 1.0,
    "tts_ttfa_ms_max": 500.0,
    "llm_tool_success_rate_min": 0.90,
    "embedding_recall_at_k_min": 0.80,
}
SUITES = ("asr", "tts", "llm", "embedding")
REQUIRED_FIELDS = {
    "asr": ("reference", "hypothesis"),
    "tts": ("audio_duration_s", "elapsed_ms", "first_audio_ms"),
    "llm": ("expected_tools", "actual_tools"),
    "embedding": ("relevant_ids", "ranked_ids", "k"),
}


def load_fixture(path: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evaluation fixture must be a JSON object")
    return payload


def load_thresholds(path: str | Path) -> dict[str, float]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("threshold configuration must be a JSON object")
    return _validated_thresholds(payload)


def _validated_thresholds(overrides: Mapping[str, Any] | None) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides is None:
        return thresholds
    unknown = sorted(set(overrides) - set(DEFAULT_THRESHOLDS))
    if unknown:
        raise ValueError(f"unknown threshold(s): {', '.join(unknown)}")
    for key, value in overrides.items():
        if isinstance(value, bool):
            raise ValueError(f"threshold {key} must be numeric")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"threshold {key} must be numeric") from exc
        if numeric < 0:
            raise ValueError(f"threshold {key} must be non-negative")
        thresholds[key] = numeric
    return thresholds


def _validate_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"evaluation fixture schema_version must be {SCHEMA_VERSION}")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or not str(metadata.get("source", "")).strip():
        raise ValueError("evaluation fixture metadata.source is required")
    models = metadata.get("models")
    if not isinstance(models, dict):
        raise ValueError("evaluation fixture metadata.models is required")
    for suite in SUITES:
        model = models.get(suite)
        if not isinstance(model, dict) or not str(model.get("provider", "")).strip() or not str(model.get("model", "")).strip():
            raise ValueError(f"evaluation fixture metadata.models.{suite} requires provider and model")
        cases = payload.get(suite)
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"evaluation fixture must contain a non-empty '{suite}' array")
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                raise ValueError(f"{suite}[{index}] must be an object")
            missing = [field for field in REQUIRED_FIELDS[suite] if field not in case]
            if missing:
                raise ValueError(f"{suite}[{index}] missing field(s): {', '.join(missing)}")
    thresholds = _validated_thresholds(payload.get("thresholds"))
    return metadata, thresholds


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _failure(metric: str, actual: float, threshold: float, comparator: str) -> dict[str, Any] | None:
    passed = actual <= threshold if comparator == "max" else actual >= threshold
    if passed:
        return None
    return {"metric": metric, "actual": actual, "threshold": threshold, "comparator": comparator}


def run_suite(
    payload: dict[str, Any],
    *,
    threshold_overrides: Mapping[str, Any] | None = None,
    fixture_path: str | Path | None = None,
) -> dict[str, Any]:
    metadata, fixture_thresholds = _validate_payload(payload)
    thresholds = _validated_thresholds({**fixture_thresholds, **(threshold_overrides or {})})

    asr_cases = payload["asr"]
    asr_wer = [token_error_rate(str(item["reference"]), str(item["hypothesis"])) for item in asr_cases]
    asr_cer = [character_error_rate(str(item["reference"]), str(item["hypothesis"])) for item in asr_cases]

    tts_cases = payload["tts"]
    tts_rtf = [real_time_factor(float(item["elapsed_ms"]), float(item["audio_duration_s"])) for item in tts_cases]
    tts_ttfa = [float(item["first_audio_ms"]) for item in tts_cases]

    llm_cases = payload["llm"]
    llm_success = [
        tool_success_rate(item.get("expected_tools", []), item.get("actual_tools", []))
        for item in llm_cases
    ]

    embedding_cases = payload["embedding"]
    embedding_recall = [
        embedding_recall_at_k(item.get("relevant_ids", []), item.get("ranked_ids", []), int(item.get("k", 5)))
        for item in embedding_cases
    ]

    metrics = {
        "asr": {"wer": _mean(asr_wer), "cer": _mean(asr_cer), "cases": len(asr_cases)},
        "tts": {"rtf": _mean(tts_rtf), "ttfa_ms": _mean(tts_ttfa), "cases": len(tts_cases)},
        "llm": {"tool_success_rate": _mean(llm_success), "cases": len(llm_cases)},
        "embedding": {"recall_at_k": _mean(embedding_recall), "cases": len(embedding_cases)},
    }
    checks = (
        ("asr.wer", metrics["asr"]["wer"], thresholds["asr_wer_max"], "max"),
        ("asr.cer", metrics["asr"]["cer"], thresholds["asr_cer_max"], "max"),
        ("tts.rtf", metrics["tts"]["rtf"], thresholds["tts_rtf_max"], "max"),
        ("tts.ttfa_ms", metrics["tts"]["ttfa_ms"], thresholds["tts_ttfa_ms_max"], "max"),
        ("llm.tool_success_rate", metrics["llm"]["tool_success_rate"], thresholds["llm_tool_success_rate_min"], "min"),
        ("embedding.recall_at_k", metrics["embedding"]["recall_at_k"], thresholds["embedding_recall_at_k_min"], "min"),
    )
    failures = [failure for metric, actual, threshold, comparator in checks if (failure := _failure(metric, actual, threshold, comparator))]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "passed": not failures,
        "metadata": metadata,
        "metrics": metrics,
        "thresholds": thresholds,
        "failures": failures,
        "run": {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    if fixture_path is not None:
        report["run"]["fixture"] = str(Path(fixture_path))
    return report

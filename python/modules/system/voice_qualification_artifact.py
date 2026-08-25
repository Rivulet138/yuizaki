"""Fail-closed persistence for redacted real-device voice qualification reports."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_SECRET_KEY_RE = re.compile(r"(?i)^(transcript|prompt|raw[_ -]?audio|credential|api[_-]?key|authorization|password|secret|token|access_token)$")
_SECRET_VALUE_RE = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]|token\s*[=:]|secret\s*[=:]|-----begin private key-----)")
_REQUIRED_FIELDS = {
    "status",
    "evidence_kind",
    "sample_count",
    "min_samples_per_stage",
    "required_stages",
    "provenance",
    "run_id",
    "matrix",
    "recovery_quality",
    "gaps",
    "claim",
}


def _assert_redacted(value: object, *, field: str = "report") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text):
                raise ValueError(f"voice qualification artifact contains restricted field: {key_text}")
            _assert_redacted(item, field=f"{field}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_redacted(item, field=f"{field}[{index}]")
        return
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise ValueError(f"voice qualification artifact contains restricted value: {field}")
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(f"voice qualification artifact contains binary value: {field}")


def _validate_report(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("voice qualification artifact is invalid")
    _assert_redacted(value)
    report = dict(value)
    if set(_REQUIRED_FIELDS) - report.keys():
        raise ValueError("voice qualification artifact is incomplete")
    if report["evidence_kind"] != "real_device":
        raise ValueError("voice qualification artifact must contain real-device evidence")
    if report["status"] not in {"qualified", "not_qualified"}:
        raise ValueError("voice qualification artifact status is invalid")
    if not isinstance(report["sample_count"], int) or report["sample_count"] < 0:
        raise ValueError("voice qualification artifact sample count is invalid")
    if not isinstance(report["matrix"], Mapping) or not isinstance(report["gaps"], list):
        raise TypeError("voice qualification artifact measurements are invalid")
    return report


class JsonVoiceQualificationArtifactStore:
    """Atomically stores redacted reports with an explicit qualification attestation."""

    def __init__(
        self,
        path: str | Path,
        *,
        attestation_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.path = Path(path)
        self.attestation_verifier = attestation_verifier

    def _authorize(self, report: Mapping[str, Any]) -> None:
        if report["status"] != "qualified":
            return
        verifier = self.attestation_verifier
        if verifier is None:
            raise ValueError("qualified voice artifact requires external attestation")
        try:
            accepted = verifier(report)
        except (OSError, RuntimeError, TypeError, ValueError):
            accepted = False
        if accepted is not True:
            raise ValueError("qualified voice artifact attestation rejected")

    def write(self, report: Mapping[str, Any]) -> None:
        safe_report = _validate_report(report)
        self._authorize(safe_report)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(safe_report, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                report = _validate_report(json.load(handle))
                self._authorize(report)
                return report
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("voice qualification artifact is corrupt") from error


__all__ = ["JsonVoiceQualificationArtifactStore"]

from __future__ import annotations

import pytest
from modules.agent.context import AgentPipelineResult
from modules.agent.failure_recovery import StepFailure
from modules.agent.step_executor import _project_non_retryable_recovery


def test_permission_failures_never_mint_automatic_recovery_authority() -> None:
    for status in ("permission_required", "permission_denied"):
        projection = _project_non_retryable_recovery(
            StepFailure(
                step_id="send-message",
                kind="permission",
                message="fresh permission is required",
                retryable=False,
                status=status,
            )
        )

        assert projection == {
            "available": False,
            "action": "request_permission",
            "failed_step_id": "send-message",
            "retryable": False,
            "confirmation_required": True,
            "reason": status,
        }
        assert "handle" not in projection
        assert "resume_token" not in projection


def test_other_non_retryable_failures_are_inspection_only() -> None:
    projection = _project_non_retryable_recovery(
        StepFailure(
            step_id="validate",
            kind="validation",
            message="invalid input",
            retryable=False,
            status="validation",
        )
    )

    assert projection["available"] is False
    assert projection["action"] == "inspect_failure"
    assert projection["confirmation_required"] is False


def test_pipeline_result_rejects_contradictory_recovery_contract() -> None:
    with pytest.raises(ValueError, match="non-retryable recovery"):
        AgentPipelineResult(
            reply="",
            outcome="failed",
            recovery={"available": True, "retryable": False},
        )

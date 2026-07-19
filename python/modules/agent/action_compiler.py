from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..pet_control import filter_pet_control_payload
from .models import ActionEnvelope, CharacterAction


def compile_action_envelope(
    *,
    reply: str,
    pet_control: dict[str, Any] | None,
    source: str = "agent",
    request_id: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions: list[CharacterAction] = []
    validated_pet_control = filter_pet_control_payload(pet_control)

    if reply:
        actions.append(CharacterAction(
            type="reply",
            content=reply,
            schema_version="yuizaki.reply.v1",
            source=source,
        ))

    if validated_pet_control:
        actions.append(CharacterAction(
            type="pet_control",
            payload=validated_pet_control,
            schema_version="yuizaki.pet-control.v1",
            source="model_validated",
        ))

    if tool_calls:
        actions.append(CharacterAction(
            type="tool_trace",
            payload=tool_calls,
            schema_version="yuizaki.tool-trace.v1",
            source="agent_runtime",
        ))

    envelope = ActionEnvelope(
        version=1,
        request_id=request_id or f"act_{uuid4().hex[:12]}",
        source=source,
        reply=reply,
        actions=actions,
    )
    return envelope.to_dict()

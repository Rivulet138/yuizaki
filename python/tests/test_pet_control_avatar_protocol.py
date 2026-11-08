from __future__ import annotations

from modules.pet_control.parser import (
    build_pet_control_response_format,
    filter_pet_control_payload,
    legacy_pet_control_to_avatar_command,
)


def _schema(context: dict) -> dict:
    return build_pet_control_response_format(context)["json_schema"]["schema"]


def _pet_control_schema(context: dict) -> dict:
    return _schema(context)["properties"]["pet_control"]["anyOf"][0]


def test_schema_is_specific_to_each_active_model_parameter_set() -> None:
    first = {
        "parameters": [{"id": "LookX", "min": -12, "max": 18}],
        "expressions": ["smile-a"],
        "motionOptions": [{"group": "IdleA", "index": 2}],
        "emotions": ["calm-a"],
    }
    second = {
        "parameters": [{"id": "HeadTilt", "min": -4, "max": 7}],
        "expressions": ["smile-b"],
        "motionOptions": [{"group": "IdleB", "index": 0}],
        "emotions": ["calm-b"],
    }

    first_schema = _pet_control_schema(first)["properties"]
    second_schema = _pet_control_schema(second)["properties"]

    assert first_schema["expression_name"]["enum"] == ["smile-a", None]
    assert second_schema["expression_name"]["enum"] == ["smile-b", None]
    first_parameter = first_schema["parameter_overrides"]["items"]["anyOf"][0]["properties"]
    second_parameter = second_schema["parameter_overrides"]["items"]["anyOf"][0]["properties"]
    assert first_parameter["id"]["enum"] == ["LookX"]
    assert first_parameter["value"]["minimum"] == -12
    assert first_parameter["value"]["maximum"] == 18
    assert second_parameter["id"]["enum"] == ["HeadTilt"]
    assert second_parameter["value"]["minimum"] == -4
    assert second_parameter["value"]["maximum"] == 7


def test_explicit_empty_capabilities_only_allow_null_action_fields() -> None:
    properties = _pet_control_schema({
        "actions": {"affect": False, "expression": False, "motion": False, "parameterPatch": False},
        "emotions": [],
        "expressions": [],
        "motionOptions": [],
        "parameters": [],
    })["properties"]

    assert properties["emotion_id"]["enum"] == [None]
    assert properties["expression_name"]["enum"] == [None]
    assert properties["motion_group"]["enum"] == [None]
    assert properties["parameter_overrides"]["items"]["properties"]["id"]["enum"] == [None]


def test_filter_rejects_unknown_values_and_does_not_substitute_motion_pair() -> None:
    context = {
        "emotions": ["calm"],
        "expressions": ["smile"],
        "motionGroups": ["Idle"],
        "motionOptions": [{"group": "Idle", "index": 2}],
        "parameters": [{"id": "LookX", "min": -12, "max": 18}],
    }

    filtered = filter_pet_control_payload({
        "emotion_id": "not-in-this-model",
        "expression_name": "not-in-this-model",
        "motion_group": "Idle",
        "motion_index": 0,
        "parameter_overrides": [{"id": "LookX", "value": 90}],
    }, context)

    assert filtered == {"parameter_overrides": [{"id": "LookX", "value": 18.0, "weight": 1.0}]}


def test_negative_motion_index_is_not_rewritten_to_zero() -> None:
    context = {
        "actions": {"motion": True},
        "motionGroups": ["Idle"],
        "motionOptions": [{"group": "Idle", "index": 0}],
    }

    filtered = filter_pet_control_payload({
        "motion_group": "Idle",
        "motion_index": -1,
        "sentence_emotions": [{"motion_group": "Idle", "motion_index": -1}],
    }, context)

    assert filtered is None


def test_expression_name_is_preserved_as_an_avatar_expression_action() -> None:
    command = legacy_pet_control_to_avatar_command(
        {"expression_name": "smile", "intensity": 0.4, "duration_ms": 900},
        command_id="cmd-1",
        stream_id="stream-1",
        sequence=1,
        issued_at=10,
    )

    assert command is not None
    assert command["actions"] == [{
        "type": "expression",
        "name": "smile",
        "weight": 0.4,
        "fadeOutMs": 900,
    }]

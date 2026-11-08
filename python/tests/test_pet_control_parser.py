from modules.pet_control.parser import (
    _normalize_parameter_overrides,
    filter_pet_control_payload,
)


def test_invalid_motion_pair_is_removed_without_substitution() -> None:
    context = {
        "emotions": ["happy"],
        "motionGroups": ["Tap", "Wave"],
        "motionOptions": [
            {"group": "Tap", "index": 0},
            {"group": "Wave", "index": 3},
        ],
    }

    filtered = filter_pet_control_payload(
        {"emotion_id": "happy", "motion_group": "Tap", "motion_index": 3},
        context,
    )

    assert filtered is not None
    assert "motion_group" not in filtered
    assert "motion_index" not in filtered


def test_sentence_invalid_motion_pair_is_removed_without_substitution() -> None:
    context = {
        "emotions": ["happy"],
        "motionGroups": ["Tap", "Wave"],
        "motionOptions": [
            {"group": "Tap", "index": 0},
            {"group": "Wave", "index": 3},
        ],
    }

    filtered = filter_pet_control_payload(
        {
            "emotion_id": "happy",
            "motion_group": "Tap",
            "motion_index": 0,
            "sentence_emotions": [
                {"sentence_index": 0, "motion_group": "Tap", "motion_index": 3}
            ],
        },
        context,
    )

    assert filtered is not None
    assert "sentence_emotions" not in filtered


def test_parameter_bounds_accept_manifest_camel_case_context() -> None:
    filtered = filter_pet_control_payload(
        {
            "emotion_id": "happy",
            "parameter_overrides": [{"id": "ParamA", "value": 8}],
        },
        {
            "emotions": ["happy"],
            "parameterControls": [{"id": "ParamA", "min": -1, "max": 1}],
        },
    )

    assert filtered is not None
    assert filtered["parameter_overrides"][0]["value"] == 1


def test_non_finite_parameter_values_are_dropped() -> None:
    assert _normalize_parameter_overrides([
        {"id": "nan", "value": float("nan")},
        {"id": "infinity", "value": float("inf")},
    ]) == []

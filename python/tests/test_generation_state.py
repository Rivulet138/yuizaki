from modules.core.state import Generation


def test_generation_pet_control_defaults_to_none_and_is_isolated() -> None:
    generation = Generation("generation", "session")
    other = Generation("other", "session")

    assert generation.pet_control is None
    generation.pet_control = {"emotion_id": "happy", "motion_index": 0}
    assert generation.pet_control == {"emotion_id": "happy", "motion_index": 0}
    assert other.pet_control is None

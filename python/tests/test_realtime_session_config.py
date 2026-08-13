from routes.realtime_api import build_realtime_session_config


def test_push_to_talk_keeps_provider_vad_disabled():
    config = build_realtime_session_config(
        model="gpt-realtime-test",
        voice="marin",
        instructions="test",
    )
    assert config["audio"]["input"]["turn_detection"] is None


def test_continuous_voice_enables_interruptible_semantic_vad():
    config = build_realtime_session_config(
        model="gpt-realtime-test",
        voice="marin",
        instructions="test",
        voice_mode="continuous",
        vad_eagerness="high",
    )
    assert config["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "create_response": True,
        "interrupt_response": True,
        "eagerness": "high",
    }


def test_invalid_vad_eagerness_falls_back_to_auto():
    config = build_realtime_session_config(
        model="gpt-realtime-test",
        voice="marin",
        instructions="test",
        voice_mode="continuous",
        vad_eagerness="invalid",
    )
    assert config["audio"]["input"]["turn_detection"]["eagerness"] == "auto"

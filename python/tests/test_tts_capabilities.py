from modules.tts.capabilities import resolve_tts_provider_capabilities


def test_genie_capabilities_distinguish_static_and_observed_features():
    capabilities = resolve_tts_provider_capabilities(
        "genie-tts",
        output_transport="pcm_s16le",
        alignment="viseme",
        observed_visemes=["ih", "AA", "ih", "unsupported"],
    )

    assert capabilities == {
        "provider": "genie-tts",
        "locality": "local",
        "input_text_streaming": False,
        "output_audio_streaming": True,
        "output_transport": "pcm_s16le",
        "alignment": "viseme",
        "viseme_vocabulary": ["aa", "ih"],
        "warmup": True,
        "cancellation": "cooperative",
    }


def test_unknown_provider_does_not_inherit_genie_capabilities():
    capabilities = resolve_tts_provider_capabilities("future-provider")

    assert capabilities["provider"] == "future-provider"
    assert capabilities["locality"] == "unknown"
    assert capabilities["output_transport"] == "unavailable"
    assert capabilities["warmup"] is False
    assert capabilities["cancellation"] == "unavailable"


def test_declared_remote_and_local_provider_contracts_are_discoverable():
    openai = resolve_tts_provider_capabilities("openai-compatible")
    assert openai["input_text_streaming"] is False
    assert openai["output_transport"] == "unavailable"
    assert openai["cancellation"] == "cooperative"

    unsupported = resolve_tts_provider_capabilities("elevenlabs")
    assert unsupported["locality"] == "unknown"
    assert unsupported["output_transport"] == "unavailable"
    assert unsupported["cancellation"] == "unavailable"

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

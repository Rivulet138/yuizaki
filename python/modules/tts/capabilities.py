from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypedDict

from modules.tts.visemes import SUPPORTED_VISEMES

TTSAlignmentMode = Literal["none", "character", "word", "viseme"]
TTSCancellationMode = Literal["cooperative", "hard", "unavailable"]
TTSLocality = Literal["local", "cloud", "unknown"]
TTSOutputTransport = Literal["pcm_s16le", "wav", "unavailable"]


class TTSProviderCapabilities(TypedDict):
    provider: str
    locality: TTSLocality
    input_text_streaming: bool
    output_audio_streaming: bool
    output_transport: TTSOutputTransport
    alignment: TTSAlignmentMode
    viseme_vocabulary: list[str]
    warmup: bool
    cancellation: TTSCancellationMode


class _TTSProviderCapabilitySpec(TypedDict):
    locality: TTSLocality
    input_text_streaming: bool
    warmup: bool
    cancellation: TTSCancellationMode


TTS_PROVIDER_CAPABILITY_REGISTRY: dict[str, _TTSProviderCapabilitySpec] = {
    "genie-tts": {
        "locality": "local",
        "input_text_streaming": False,
        "warmup": True,
        "cancellation": "cooperative",
    },
}


def resolve_tts_provider_capabilities(
    provider: str,
    *,
    output_transport: TTSOutputTransport = "unavailable",
    alignment: TTSAlignmentMode = "none",
    observed_visemes: Iterable[str] = (),
) -> TTSProviderCapabilities:
    normalized_provider = provider.strip().lower()
    spec = TTS_PROVIDER_CAPABILITY_REGISTRY.get(normalized_provider)
    if spec is None:
        spec = {
            "locality": "unknown",
            "input_text_streaming": False,
            "warmup": False,
            "cancellation": "unavailable",
        }

    normalized_visemes = {
        str(viseme).strip().lower()
        for viseme in observed_visemes
    }
    vocabulary = (
        sorted(normalized_visemes.intersection(SUPPORTED_VISEMES))
        if alignment == "viseme"
        else []
    )
    return {
        "provider": normalized_provider,
        "locality": spec["locality"],
        "input_text_streaming": spec["input_text_streaming"],
        "output_audio_streaming": output_transport == "pcm_s16le",
        "output_transport": output_transport,
        "alignment": alignment,
        "viseme_vocabulary": vocabulary,
        "warmup": spec["warmup"],
        "cancellation": spec["cancellation"],
    }

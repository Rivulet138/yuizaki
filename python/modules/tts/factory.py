from __future__ import annotations

from pathlib import Path

from modules.tts.openai_compatible import OpenAICompatibleTTSClient
from modules.tts.provider import TTSProviderClient
from modules.tts.synthesizer import TTSClient
from modules.system.voice_diagnostics import VoiceDiagnostics


def create_tts_client(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    voice: str,
    timeout: float,
    genie_character: str,
    genie_model_dir: str | None,
    language: str,
    ref_audio: str,
    ref_text: str,
    device: str,
    quality: str,
    split: str,
    mode: str,
    save_mode: str,
    audio_cache_dir: Path,
    diagnostics: VoiceDiagnostics | None = None,
) -> TTSProviderClient:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "openai-compatible":
        return OpenAICompatibleTTSClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            voice=voice,
            timeout=timeout,
            audio_cache_dir=audio_cache_dir,
            diagnostics=diagnostics,
        )
    if normalized_provider != "genie-tts":
        raise ValueError(f"Unsupported TTS provider: {provider}")
    return TTSClient(
        genie_character=genie_character,
        genie_model_dir=genie_model_dir,
        language=language,
        ref_audio=ref_audio,
        ref_text=ref_text,
        device=device,
        quality=quality,
        split=split,
        mode=mode,
        save_mode=save_mode,
        audio_cache_dir=audio_cache_dir,
        diagnostics=diagnostics,
    )

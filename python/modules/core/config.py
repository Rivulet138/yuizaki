"""
Configuration management for Yuizaki backend.
Loads from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

from .paths import DEFAULT_AUDIO_CACHE_DIR, audio_cache_dir_from_env, data_dir_from_env
SUMMARY_ADMIN_TOKEN_PLACEHOLDERS = {"your-admin-token-here"}
DEFAULT_TTS_LANG = "ja"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_QDRANT_DOCKER_IMAGE = "qdrant/qdrant:latest"
DEFAULT_QDRANT_DOCKER_CONTAINER = "yuizaki-qdrant"
DEFAULT_QDRANT_DOCKER_VOLUME = "yuizaki-qdrant-storage"
DEFAULT_MEMORY_SQLITE_PATH = data_dir_from_env() / "memory.db"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_optional_secret(value: str | None, placeholders: set[str]) -> str:
    clean = (value or "").strip()
    return "" if clean.lower() in placeholders else clean


class LLMConfig(BaseModel):
    """LLM service configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str = Field(default="custom")
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    model: str = Field(default="")
    timeout: float = Field(default=60.0)
    context_max_tokens: int = Field(default=131072)
    default_max_output_tokens: int = Field(default=8192)
    temperature: float = Field(default=1.2)
    top_p: float = Field(default=0.9)
    top_k: int = Field(default=500)
    min_p: float = Field(default=0.0)
    frequency_penalty: float = Field(default=0.2)
    presence_penalty: float = Field(default=0.0)
    repetition_penalty: float = Field(default=1.0)
    vision_enabled: bool = Field(default=False)
    vision_provider: str = Field(default="custom")
    vision_base_url: str = Field(default="")
    vision_api_key: str = Field(default="")
    vision_model: str = Field(default="")
    vision_timeout: float = Field(default=30.0)


class TTSConfig(BaseModel):
    """TTS service configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    genie_character: str = Field(default="")
    genie_model_dir: str = Field(default="")
    ref_audio: str = Field(default="")
    ref_text: str = Field(default="")
    lang: str = Field(default=DEFAULT_TTS_LANG)
    device: str = Field(default="cpu")
    quality: str = Field(default="质量优先")
    split: str = Field(default="智能切分")
    mode: str = Field(default="串行推理")
    save_mode: str = Field(default="禁用自动保存")
    provider: str = Field(default="genie-tts")
    audio_cache_dir: Path = Field(default=DEFAULT_AUDIO_CACHE_DIR)


class ASRConfig(BaseModel):
    """ASR (Automatic Speech Recognition) configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str = Field(default="sensevoice-service")
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    timeout: float = Field(default=60.0)
    sensevoice_model: str = Field(default="iic/SenseVoiceSmall")
    sensevoice_device: str = Field(default="cpu")
    sherpa_model_path: str = Field(default="")
    sherpa_tokens_path: str = Field(default="")
    sherpa_num_threads: int = Field(default=2)
    sherpa_provider: str = Field(default="cpu")
    language: str = Field(default="zh")
    vad_threshold: float = Field(default=0.5)
    vad_min_silence_ms: int = Field(default=300)
    asr_partial_every: int = Field(default=15)


class SVCConfig(BaseModel):
    """SVC (Singing Voice Conversion) configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str = Field(default="soulx-service")
    base_url: str = Field(default="")
    speaker_id: int = Field(default=0)
    pitch: int = Field(default=0)
    timeout: float = Field(default=120.0)


class CacheConfig(BaseModel):
    """Cache and cleanup configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    max_age: int = Field(default=1800)
    janitor_interval: int = Field(default=600)


class SummaryConfig(BaseModel):
    """Summary governance configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trigger_messages: int = Field(default=24)
    keep_recent_messages: int = Field(default=8)
    item_max_chars: int = Field(default=140)
    rewrite_interval_messages: int = Field(default=6)
    admin_token: str = Field(default="")
    quality_scorer_mode: str = Field(default="rule")
    quality_score_cooldown_seconds: int = Field(default=300)
    quality_score_budget_per_hour: int = Field(default=20)


class MemoryConfig(BaseModel):
    """Memory / RAG backend configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    backend: str = Field(default="sqlite")
    sqlite_path: str = Field(default=str(DEFAULT_MEMORY_SQLITE_PATH))
    qdrant_url: str = Field(default="")
    qdrant_api_key: str = Field(default="")
    qdrant_collection: str = Field(default="memories")
    qdrant_timeout: float = Field(default=10.0)
    qdrant_auto_start: bool = Field(default=True)
    qdrant_docker_image: str = Field(default=DEFAULT_QDRANT_DOCKER_IMAGE)
    qdrant_docker_container: str = Field(default=DEFAULT_QDRANT_DOCKER_CONTAINER)
    qdrant_docker_volume: str = Field(default=DEFAULT_QDRANT_DOCKER_VOLUME)
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL)


class AppConfig(BaseModel):
    """Main application configuration."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    svc: SVCConfig = Field(default_factory=SVCConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)


def public_config_snapshot(value: AppConfig) -> dict[str, object]:
    payload = value.model_dump(mode="json")
    secret_fields = {
        "llm": ("api_key", "vision_api_key"),
        "asr": ("api_key",),
        "summary": ("admin_token",),
        "memory": ("qdrant_api_key",),
    }
    for section_name, fields in secret_fields.items():
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for field_name in fields:
            section[f"{field_name}_configured"] = bool(section.pop(field_name, ""))
    return payload


def _load_config_from_env() -> AppConfig:
    """Load configuration from environment variables."""
    return AppConfig(
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "custom").strip().lower(),
            base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", ""),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
            context_max_tokens=int(os.getenv("LLM_CONTEXT_MAX_TOKENS", "131072")),
            default_max_output_tokens=int(os.getenv("LLM_DEFAULT_MAX_OUTPUT_TOKENS", "8192")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "1.2")),
            top_p=float(os.getenv("LLM_TOP_P", "0.9")),
            top_k=int(os.getenv("LLM_TOP_K", "500")),
            min_p=float(os.getenv("LLM_MIN_P", "0")),
            frequency_penalty=float(os.getenv("LLM_FREQUENCY_PENALTY", "0.2")),
            presence_penalty=float(os.getenv("LLM_PRESENCE_PENALTY", "0")),
            repetition_penalty=float(os.getenv("LLM_REPETITION_PENALTY", "1")),
            vision_enabled=_env_bool("VISION_LLM_ENABLED", False),
            vision_provider=os.getenv("VISION_LLM_PROVIDER", "custom").strip().lower(),
            vision_base_url=os.getenv("VISION_LLM_BASE_URL", "").rstrip("/"),
            vision_api_key=os.getenv("VISION_LLM_API_KEY", ""),
            vision_model=os.getenv("VISION_LLM_MODEL", ""),
            vision_timeout=float(os.getenv("VISION_LLM_TIMEOUT", "30")),
        ),
        tts=TTSConfig(
            genie_character=os.getenv("TTS_GENIE_CHARACTER", ""),
            genie_model_dir=os.getenv("TTS_GENIE_MODEL_DIR", ""),
            ref_audio=os.getenv("TTS_REF_AUDIO", ""),
            ref_text=os.getenv("TTS_REF_TEXT", ""),
            lang=os.getenv("TTS_LANG", DEFAULT_TTS_LANG),
            device=os.getenv("TTS_DEVICE", "cpu"),
            quality=os.getenv("TTS_QUALITY", "质量优先"),
            split=os.getenv("TTS_SPLIT", "智能切分"),
            mode=os.getenv("TTS_MODE", "串行推理"),
            save_mode=os.getenv("TTS_SAVE_MODE", "禁用自动保存"),
            provider=os.getenv("TTS_PROVIDER", "genie-tts"),
            audio_cache_dir=audio_cache_dir_from_env(),
        ),
        asr=ASRConfig(
            provider=os.getenv("ASR_PROVIDER", "sensevoice-service").strip().lower(),
            base_url=os.getenv("ASR_BASE_URL", "").rstrip("/"),
            api_key=os.getenv("ASR_API_KEY", ""),
            timeout=float(os.getenv("ASR_TIMEOUT", "60")),
            sensevoice_model=os.getenv("SENSEVOICE_MODEL", "iic/SenseVoiceSmall"),
            sensevoice_device=os.getenv("SENSEVOICE_DEVICE", "cpu"),
            sherpa_model_path=os.getenv("SHERPA_ONNX_MODEL_PATH", ""),
            sherpa_tokens_path=os.getenv("SHERPA_ONNX_TOKENS_PATH", ""),
            sherpa_num_threads=int(os.getenv("SHERPA_ONNX_NUM_THREADS", "2")),
            sherpa_provider=os.getenv("SHERPA_ONNX_PROVIDER", "cpu").strip().lower(),
            language=os.getenv("ASR_LANGUAGE", "zh"),
            vad_threshold=float(os.getenv("VAD_THRESHOLD", "0.5")),
            vad_min_silence_ms=int(os.getenv("VAD_MIN_SILENCE_MS", "300")),
            asr_partial_every=int(os.getenv("ASR_PARTIAL_EVERY", "15")),
        ),
        svc=SVCConfig(
            provider=os.getenv("SVC_PROVIDER", "soulx-service").strip().lower(),
            base_url=os.getenv("SVC_BASE_URL", "").rstrip("/"),
            speaker_id=int(os.getenv("SVC_SPEAKER_ID", "0")),
            pitch=int(os.getenv("SVC_PITCH", "0")),
            timeout=float(os.getenv("SVC_TIMEOUT", "120")),
        ),
        cache=CacheConfig(
            max_age=int(os.getenv("CACHE_MAX_AGE", "1800")),
            janitor_interval=int(os.getenv("CACHE_JANITOR_INTERVAL", "600")),
        ),
        summary=SummaryConfig(
            trigger_messages=int(os.getenv("SUMMARY_TRIGGER_MESSAGES", "24")),
            keep_recent_messages=int(os.getenv("SUMMARY_KEEP_RECENT_MESSAGES", "8")),
            item_max_chars=int(os.getenv("SUMMARY_ITEM_MAX_CHARS", "140")),
            rewrite_interval_messages=int(os.getenv("SUMMARY_REWRITE_INTERVAL_MESSAGES", "6")),
            admin_token=_clean_optional_secret(os.getenv("SUMMARY_ADMIN_TOKEN", ""), SUMMARY_ADMIN_TOKEN_PLACEHOLDERS),
            quality_scorer_mode=os.getenv("SUMMARY_QUALITY_SCORER_MODE", "rule").strip().lower(),
            quality_score_cooldown_seconds=int(os.getenv("SUMMARY_QUALITY_SCORE_COOLDOWN_SECONDS", "300")),
            quality_score_budget_per_hour=int(os.getenv("SUMMARY_QUALITY_SCORE_BUDGET_PER_HOUR", "20")),
        ),
        memory=MemoryConfig(
            backend=os.getenv("MEMORY_BACKEND", "sqlite").strip().lower(),
            sqlite_path=os.getenv("MEMORY_SQLITE_PATH", str(DEFAULT_MEMORY_SQLITE_PATH)).strip() or str(DEFAULT_MEMORY_SQLITE_PATH),
            qdrant_url=os.getenv("QDRANT_URL", "").rstrip("/"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "memories").strip() or "memories",
            qdrant_timeout=float(os.getenv("QDRANT_TIMEOUT", "10")),
            qdrant_auto_start=_env_bool("QDRANT_AUTO_START", True),
            qdrant_docker_image=os.getenv("QDRANT_DOCKER_IMAGE", DEFAULT_QDRANT_DOCKER_IMAGE).strip() or DEFAULT_QDRANT_DOCKER_IMAGE,
            qdrant_docker_container=os.getenv("QDRANT_DOCKER_CONTAINER", DEFAULT_QDRANT_DOCKER_CONTAINER).strip() or DEFAULT_QDRANT_DOCKER_CONTAINER,
            qdrant_docker_volume=os.getenv("QDRANT_DOCKER_VOLUME", DEFAULT_QDRANT_DOCKER_VOLUME).strip() or DEFAULT_QDRANT_DOCKER_VOLUME,
            embedding_model=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL,
        ),
    )


# Global config instance
config = _load_config_from_env()

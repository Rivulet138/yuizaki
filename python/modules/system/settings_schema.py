from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..core.config import (
    DEFAULT_QDRANT_DOCKER_CONTAINER,
    DEFAULT_QDRANT_DOCKER_IMAGE,
    DEFAULT_QDRANT_DOCKER_VOLUME,
    DEFAULT_TTS_LANG,
    config as env_config,
)
from ..llm.providers import normalize_llm_base_url, normalize_llm_provider

LLMProvider = Literal["deepseek", "qwen", "gemini", "chatgpt", "claude", "grok", "ollama", "lmstudio", "custom"]
KEYLESS_LLM_PROVIDERS = {"ollama", "lmstudio"}
TTS_PROVIDER = "genie-tts"
TTS_SAVE_MODE = "禁用自动保存"


class LLMProviderProfileModel(BaseModel):
    provider: LLMProvider | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout: float | None = None
    context_max_tokens: int | None = None
    default_max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider_input(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_llm_provider(value)

    def model_post_init(self, _context: Any) -> None:
        if self.provider is not None:
            self.provider = normalize_llm_provider(self.provider, self.base_url or "")  # type: ignore[assignment]
        if self.base_url is not None:
            self.base_url = normalize_llm_base_url(self.base_url, self.provider or "custom")
        if self.provider in KEYLESS_LLM_PROVIDERS:
            self.api_key = ""


def _normalized_llm_profiles(profiles: dict[str, LLMProviderProfileModel]) -> dict[str, LLMProviderProfileModel]:
    normalized: dict[str, LLMProviderProfileModel] = {}
    for raw_key, profile in profiles.items():
        profile_key = normalize_llm_provider(raw_key, profile.base_url or "")
        if profile.provider is None:
            profile.provider = profile_key  # type: ignore[assignment]
        if profile.base_url is None:
            profile.base_url = normalize_llm_base_url("", profile_key) or None
        if profile.provider in KEYLESS_LLM_PROVIDERS or profile_key in KEYLESS_LLM_PROVIDERS:
            profile.provider = profile_key  # type: ignore[assignment]
            profile.api_key = ""
        normalized[profile_key] = profile
    return normalized


class LLMSettingsModel(BaseModel):
    provider: LLMProvider = Field(default_factory=lambda: normalize_llm_provider(env_config.llm.provider, env_config.llm.base_url))  # type: ignore[arg-type]
    base_url: str = Field(default_factory=lambda: env_config.llm.base_url)
    api_key: str = Field(default_factory=lambda: env_config.llm.api_key)
    model: str = Field(default_factory=lambda: env_config.llm.model)
    timeout: float = Field(default_factory=lambda: env_config.llm.timeout)
    context_max_tokens: int = Field(default_factory=lambda: env_config.llm.context_max_tokens)
    default_max_output_tokens: int = Field(default_factory=lambda: env_config.llm.default_max_output_tokens)
    temperature: float = Field(default_factory=lambda: env_config.llm.temperature)
    top_p: float = Field(default_factory=lambda: env_config.llm.top_p)
    top_k: int = Field(default_factory=lambda: env_config.llm.top_k)
    min_p: float = Field(default_factory=lambda: env_config.llm.min_p)
    frequency_penalty: float = Field(default_factory=lambda: env_config.llm.frequency_penalty)
    presence_penalty: float = Field(default_factory=lambda: env_config.llm.presence_penalty)
    repetition_penalty: float = Field(default_factory=lambda: env_config.llm.repetition_penalty)
    vision_enabled: bool = Field(default_factory=lambda: env_config.llm.vision_enabled)
    vision_provider: LLMProvider = Field(default_factory=lambda: normalize_llm_provider(env_config.llm.vision_provider, env_config.llm.vision_base_url))  # type: ignore[arg-type]
    vision_base_url: str = Field(default_factory=lambda: env_config.llm.vision_base_url)
    vision_api_key: str = Field(default_factory=lambda: env_config.llm.vision_api_key)
    vision_model: str = Field(default_factory=lambda: env_config.llm.vision_model)
    vision_timeout: float = Field(default_factory=lambda: env_config.llm.vision_timeout, gt=0)
    profiles: dict[str, LLMProviderProfileModel] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "vision_provider", mode="before")
    @classmethod
    def _normalize_provider_input(cls, value: Any) -> str:
        return normalize_llm_provider(value)

    def model_post_init(self, _context: Any) -> None:
        self.provider = normalize_llm_provider(self.provider, self.base_url)  # type: ignore[assignment]
        self.base_url = normalize_llm_base_url(self.base_url, self.provider)
        if self.provider in KEYLESS_LLM_PROVIDERS:
            self.api_key = ""
        self.vision_provider = normalize_llm_provider(self.vision_provider, self.vision_base_url)  # type: ignore[assignment]
        self.vision_base_url = normalize_llm_base_url(self.vision_base_url, self.vision_provider)
        if self.vision_provider in KEYLESS_LLM_PROVIDERS:
            self.vision_api_key = ""
        self.profiles = _normalized_llm_profiles(self.profiles)


TTSLanguage = Literal["zh", "ja", "en", "auto"]
TTSDevice = Literal["cpu", "cuda"]
ASRProvider = Literal["sensevoice-service", "funasr-service", "openai-compatible", "sherpa-onnx", "sherpa-onnx-online", "sensevoice-local", "disabled"]
SherpaProvider = Literal["cpu", "cuda", "coreml"]
SVCProvider = Literal["soulx-service", "disabled"]
WhisperDevice = Literal["cuda", "cpu"]
QualityScorerMode = Literal["rule", "llm"]
MemoryBackend = Literal["sqlite", "inmemory", "qdrant"]
UISystemLanguage = Literal["zh-CN", "zh", "en", "en-US", "ja", "ja-JP"]
UISystemTheme = Literal["light", "dark", "system"]

_TTS_LANGUAGE_OPTIONS: dict[str, TTSLanguage] = {"zh": "zh", "ja": "ja", "en": "en", "auto": "auto"}
_TTS_DEVICE_OPTIONS: dict[str, TTSDevice] = {"cpu": "cpu", "cuda": "cuda"}
_ASR_PROVIDER_OPTIONS: dict[str, ASRProvider] = {
    "sensevoice-service": "sensevoice-service",
    "funasr-service": "funasr-service",
    "openai-compatible": "openai-compatible",
    "sherpa-onnx": "sherpa-onnx",
    "sherpa-onnx-online": "sherpa-onnx-online",
    "sensevoice-local": "sensevoice-local",
    "disabled": "disabled",
}
_SVC_PROVIDER_OPTIONS: dict[str, SVCProvider] = {
    "soulx-service": "soulx-service",
    "disabled": "disabled",
}
_DEVICE_OPTIONS: dict[str, WhisperDevice] = {"cuda": "cuda", "cpu": "cpu"}
_SHERPA_PROVIDER_OPTIONS: dict[str, SherpaProvider] = {"cpu": "cpu", "cuda": "cuda", "coreml": "coreml"}
_QUALITY_SCORER_OPTIONS: dict[str, QualityScorerMode] = {"rule": "rule", "llm": "llm"}
_MEMORY_BACKEND_OPTIONS: dict[str, MemoryBackend] = {
    "sqlite": "sqlite",
    "inmemory": "inmemory",
    "qdrant": "qdrant",
}


def _tts_language_default() -> TTSLanguage:
    return _TTS_LANGUAGE_OPTIONS.get(env_config.tts.lang, DEFAULT_TTS_LANG)


def _tts_device_default() -> TTSDevice:
    return _TTS_DEVICE_OPTIONS.get(env_config.tts.device.strip().lower(), "cpu")


def _asr_provider_default() -> ASRProvider:
    return _ASR_PROVIDER_OPTIONS.get(env_config.asr.provider.strip().lower(), "sensevoice-service")


def _svc_provider_default() -> SVCProvider:
    return _SVC_PROVIDER_OPTIONS.get(env_config.svc.provider, "soulx-service")


def _sherpa_provider_default() -> SherpaProvider:
    return _SHERPA_PROVIDER_OPTIONS.get(env_config.asr.sherpa_provider.strip().lower(), "cpu")


def _quality_scorer_mode_default() -> QualityScorerMode:
    return _QUALITY_SCORER_OPTIONS.get(env_config.summary.quality_scorer_mode, "rule")


def _memory_backend_default() -> MemoryBackend:
    return _MEMORY_BACKEND_OPTIONS.get(env_config.memory.backend, "sqlite")


class TTSSettingsModel(BaseModel):
    genie_character: str = Field(default_factory=lambda: env_config.tts.genie_character)
    genie_model_dir: str = Field(default_factory=lambda: env_config.tts.genie_model_dir)
    lang: TTSLanguage = Field(default_factory=_tts_language_default)
    ref_audio: str = Field(default_factory=lambda: env_config.tts.ref_audio)
    ref_text: str = Field(default_factory=lambda: env_config.tts.ref_text)
    device: TTSDevice = Field(default_factory=_tts_device_default)
    quality: str = Field(default_factory=lambda: env_config.tts.quality)
    split: str = Field(default_factory=lambda: env_config.tts.split)
    mode: str = Field(default_factory=lambda: env_config.tts.mode)
    save_mode: str = Field(default=TTS_SAVE_MODE)
    provider: str = Field(default=TTS_PROVIDER)

    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, __context: Any) -> None:
        self.provider = TTS_PROVIDER
        self.save_mode = TTS_SAVE_MODE


class ASRSettingsModel(BaseModel):
    provider: ASRProvider = Field(default_factory=_asr_provider_default)
    base_url: str = Field(default_factory=lambda: env_config.asr.base_url)
    api_key: str = Field(default_factory=lambda: env_config.asr.api_key)
    timeout: float = Field(default_factory=lambda: env_config.asr.timeout)
    sensevoice_model: str = Field(default_factory=lambda: env_config.asr.sensevoice_model)
    sensevoice_device: WhisperDevice = Field(default_factory=lambda: _DEVICE_OPTIONS.get(env_config.asr.sensevoice_device, "cpu"))
    sherpa_model_path: str = Field(default_factory=lambda: env_config.asr.sherpa_model_path)
    sherpa_tokens_path: str = Field(default_factory=lambda: env_config.asr.sherpa_tokens_path)
    sherpa_num_threads: int = Field(default_factory=lambda: env_config.asr.sherpa_num_threads)
    sherpa_provider: SherpaProvider = Field(default_factory=_sherpa_provider_default)
    language: str = Field(default_factory=lambda: env_config.asr.language)
    vad_threshold: float = Field(default_factory=lambda: env_config.asr.vad_threshold)
    vad_min_silence_ms: int = Field(default_factory=lambda: env_config.asr.vad_min_silence_ms)
    asr_partial_every: int = Field(default_factory=lambda: env_config.asr.asr_partial_every)

    model_config = ConfigDict(extra="forbid")

    @field_validator("vad_threshold", mode="before")
    @classmethod
    def _normalize_vad_threshold(cls, value: Any) -> float:
        return max(0.1, min(0.9, float(value)))

    @field_validator("vad_min_silence_ms", mode="before")
    @classmethod
    def _normalize_vad_silence(cls, value: Any) -> int:
        return max(160, min(1200, int(value)))

    @field_validator("asr_partial_every", mode="before")
    @classmethod
    def _normalize_partial_interval(cls, value: Any) -> int:
        return max(1, min(30, int(value)))


class SVCSettingsModel(BaseModel):
    provider: SVCProvider = Field(default_factory=_svc_provider_default)
    base_url: str = Field(default_factory=lambda: env_config.svc.base_url)
    speaker_id: int = Field(default_factory=lambda: env_config.svc.speaker_id)
    pitch: int = Field(default_factory=lambda: env_config.svc.pitch)
    timeout: float = Field(default_factory=lambda: env_config.svc.timeout)

    model_config = ConfigDict(extra="forbid")


class SummarySettingsModel(BaseModel):
    trigger_messages: int = Field(default_factory=lambda: env_config.summary.trigger_messages)
    keep_recent_messages: int = Field(default_factory=lambda: env_config.summary.keep_recent_messages)
    item_max_chars: int = Field(default_factory=lambda: env_config.summary.item_max_chars)
    rewrite_interval_messages: int = Field(default_factory=lambda: env_config.summary.rewrite_interval_messages)
    quality_scorer_mode: QualityScorerMode = Field(default_factory=_quality_scorer_mode_default)
    quality_score_cooldown_seconds: int = Field(default_factory=lambda: env_config.summary.quality_score_cooldown_seconds)
    quality_score_budget_per_hour: int = Field(default_factory=lambda: env_config.summary.quality_score_budget_per_hour)

    model_config = ConfigDict(extra="forbid")


class UISystemSettingsModel(BaseModel):
    language: UISystemLanguage = "zh-CN"
    theme: UISystemTheme = "light"

    model_config = ConfigDict(extra="forbid")


class MemorySettingsModel(BaseModel):
    backend: MemoryBackend = Field(default_factory=_memory_backend_default)
    sqlite_path: str = Field(default_factory=lambda: env_config.memory.sqlite_path)
    qdrant_url: str = Field(default_factory=lambda: env_config.memory.qdrant_url)
    qdrant_api_key: str = Field(default_factory=lambda: env_config.memory.qdrant_api_key)
    qdrant_collection: str = Field(default_factory=lambda: env_config.memory.qdrant_collection)
    qdrant_timeout: float = Field(default_factory=lambda: env_config.memory.qdrant_timeout, gt=0)
    qdrant_auto_start: bool = Field(default_factory=lambda: env_config.memory.qdrant_auto_start)
    qdrant_docker_image: str = Field(default_factory=lambda: env_config.memory.qdrant_docker_image or DEFAULT_QDRANT_DOCKER_IMAGE)
    qdrant_docker_container: str = Field(default_factory=lambda: env_config.memory.qdrant_docker_container or DEFAULT_QDRANT_DOCKER_CONTAINER)
    qdrant_docker_volume: str = Field(default_factory=lambda: env_config.memory.qdrant_docker_volume or DEFAULT_QDRANT_DOCKER_VOLUME)
    embedding_model: str = Field(default_factory=lambda: env_config.memory.embedding_model)

    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, _context: Any) -> None:
        self.qdrant_url = self.qdrant_url.rstrip("/")
        self.qdrant_collection = self.qdrant_collection.strip() or "memories"
        self.qdrant_docker_image = self.qdrant_docker_image.strip() or DEFAULT_QDRANT_DOCKER_IMAGE
        self.qdrant_docker_container = self.qdrant_docker_container.strip() or DEFAULT_QDRANT_DOCKER_CONTAINER
        self.qdrant_docker_volume = self.qdrant_docker_volume.strip() or DEFAULT_QDRANT_DOCKER_VOLUME


class LLMSettingsPatchModel(BaseModel):
    provider: LLMProvider | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout: float | None = None
    context_max_tokens: int | None = None
    default_max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    vision_enabled: bool | None = None
    vision_provider: LLMProvider | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_model: str | None = None
    vision_timeout: float | None = None
    profiles: dict[str, LLMProviderProfileModel] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "vision_provider", mode="before")
    @classmethod
    def _normalize_provider_input(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_llm_provider(value)

    def model_post_init(self, _context: Any) -> None:
        if self.provider is not None:
            self.provider = normalize_llm_provider(self.provider, self.base_url or "")  # type: ignore[assignment]
        if self.base_url is not None:
            self.base_url = normalize_llm_base_url(self.base_url, self.provider or "custom")
        if self.provider in KEYLESS_LLM_PROVIDERS:
            self.api_key = ""
            self.__pydantic_fields_set__.add("api_key")
        if self.vision_provider is not None:
            self.vision_provider = normalize_llm_provider(self.vision_provider, self.vision_base_url or "")  # type: ignore[assignment]
        if self.vision_base_url is not None:
            self.vision_base_url = normalize_llm_base_url(self.vision_base_url, self.vision_provider or "custom")
        if self.vision_provider in KEYLESS_LLM_PROVIDERS:
            self.vision_api_key = ""
            self.__pydantic_fields_set__.add("vision_api_key")
        if self.profiles is not None:
            self.profiles = _normalized_llm_profiles(self.profiles)


class TTSSettingsPatchModel(BaseModel):
    genie_character: str | None = None
    genie_model_dir: str | None = None
    lang: TTSLanguage | None = None
    ref_audio: str | None = None
    ref_text: str | None = None
    device: TTSDevice | None = None
    quality: str | None = None
    split: str | None = None
    mode: str | None = None
    save_mode: str | None = None
    provider: str | None = None

    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, __context: Any) -> None:
        if self.provider is not None:
            self.provider = TTS_PROVIDER
        if self.save_mode is not None:
            self.save_mode = TTS_SAVE_MODE


class ASRSettingsPatchModel(BaseModel):
    provider: ASRProvider | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    sensevoice_model: str | None = None
    sensevoice_device: WhisperDevice | None = None
    sherpa_model_path: str | None = None
    sherpa_tokens_path: str | None = None
    sherpa_num_threads: int | None = None
    sherpa_provider: SherpaProvider | None = None
    language: str | None = None
    vad_threshold: float | None = None
    vad_min_silence_ms: int | None = None
    asr_partial_every: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("vad_threshold", mode="before")
    @classmethod
    def _normalize_optional_vad_threshold(cls, value: Any) -> float | None:
        return None if value is None else max(0.1, min(0.9, float(value)))

    @field_validator("vad_min_silence_ms", mode="before")
    @classmethod
    def _normalize_optional_vad_silence(cls, value: Any) -> int | None:
        return None if value is None else max(160, min(1200, int(value)))

    @field_validator("asr_partial_every", mode="before")
    @classmethod
    def _normalize_optional_partial_interval(cls, value: Any) -> int | None:
        return None if value is None else max(1, min(30, int(value)))


class SVCSettingsPatchModel(BaseModel):
    provider: SVCProvider | None = None
    base_url: str | None = None
    speaker_id: int | None = None
    pitch: int | None = None
    timeout: float | None = None

    model_config = ConfigDict(extra="forbid")


class SummarySettingsPatchModel(BaseModel):
    trigger_messages: int | None = None
    keep_recent_messages: int | None = None
    item_max_chars: int | None = None
    rewrite_interval_messages: int | None = None
    quality_scorer_mode: QualityScorerMode | None = None
    quality_score_cooldown_seconds: int | None = None
    quality_score_budget_per_hour: int | None = None

    model_config = ConfigDict(extra="forbid")


class MemorySettingsPatchModel(BaseModel):
    backend: MemoryBackend | None = None
    sqlite_path: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None
    qdrant_timeout: float | None = Field(default=None, gt=0)
    qdrant_auto_start: bool | None = None
    qdrant_docker_image: str | None = None
    qdrant_docker_container: str | None = None
    qdrant_docker_volume: str | None = None
    embedding_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, _context: Any) -> None:
        if self.qdrant_url is not None:
            self.qdrant_url = self.qdrant_url.rstrip("/")
        if self.qdrant_collection is not None:
            self.qdrant_collection = self.qdrant_collection.strip() or "memories"
        if self.qdrant_docker_image is not None:
            self.qdrant_docker_image = self.qdrant_docker_image.strip() or DEFAULT_QDRANT_DOCKER_IMAGE
        if self.qdrant_docker_container is not None:
            self.qdrant_docker_container = self.qdrant_docker_container.strip() or DEFAULT_QDRANT_DOCKER_CONTAINER
        if self.qdrant_docker_volume is not None:
            self.qdrant_docker_volume = self.qdrant_docker_volume.strip() or DEFAULT_QDRANT_DOCKER_VOLUME


class UISystemSettingsPatchModel(BaseModel):
    language: UISystemLanguage | None = None
    theme: UISystemTheme | None = None

    model_config = ConfigDict(extra="forbid")


class RuntimeSettingsPatch(BaseModel):
    llm: LLMSettingsPatchModel | None = None
    tts: TTSSettingsPatchModel | None = None
    asr: ASRSettingsPatchModel | None = None
    svc: SVCSettingsPatchModel | None = None
    summary: SummarySettingsPatchModel | None = None
    memory: MemorySettingsPatchModel | None = None
    system: UISystemSettingsPatchModel | None = None

    model_config = ConfigDict(extra="forbid")


class PersistedSettingsSchema(BaseModel):
    llm: LLMSettingsModel = Field(default_factory=LLMSettingsModel)
    tts: TTSSettingsModel = Field(default_factory=TTSSettingsModel)
    asr: ASRSettingsModel = Field(default_factory=ASRSettingsModel)
    svc: SVCSettingsModel = Field(default_factory=SVCSettingsModel)
    summary: SummarySettingsModel = Field(default_factory=SummarySettingsModel)
    memory: MemorySettingsModel = Field(default_factory=MemorySettingsModel)
    system: UISystemSettingsModel = Field(default_factory=UISystemSettingsModel)

    model_config = ConfigDict(extra="forbid")


def merge_settings(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_settings(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def validate_persisted_settings(payload: dict[str, Any]) -> PersistedSettingsSchema:
    return PersistedSettingsSchema.model_validate(payload)



def validate_runtime_patch(payload: dict[str, Any]) -> RuntimeSettingsPatch:
    return RuntimeSettingsPatch.model_validate(payload)


def validation_errors_to_detail(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()]

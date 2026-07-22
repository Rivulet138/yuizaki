from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from ..core.config import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_QDRANT_DOCKER_CONTAINER,
    DEFAULT_QDRANT_DOCKER_IMAGE,
    DEFAULT_QDRANT_DOCKER_VOLUME,
)
from ..llm.providers import normalize_llm_base_url, normalize_llm_provider


class LLMRuntimeConfig(Protocol):
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout: float
    context_max_tokens: int
    default_max_output_tokens: int
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    frequency_penalty: float
    presence_penalty: float
    repetition_penalty: float
    vision_enabled: bool
    vision_provider: str
    vision_base_url: str
    vision_api_key: str
    vision_model: str
    vision_timeout: float
    vision_detail: str


class TTSRuntimeConfig(Protocol):
    genie_character: str
    genie_model_dir: str
    base_url: str
    ref_audio: str
    ref_text: str
    lang: str
    timeout: float
    speed: float
    volume: float
    device: str
    quality: str
    split: str
    mode: str
    save_mode: str
    provider: str
    voice: str


class ASRRuntimeConfig(Protocol):
    provider: str
    base_url: str
    api_key: str
    timeout: float
    sensevoice_model: str
    sensevoice_device: str
    sherpa_model_path: str
    sherpa_tokens_path: str
    sherpa_num_threads: int
    sherpa_provider: str
    language: str
    vad_threshold: float
    vad_min_silence_ms: int
    asr_partial_every: int


class SVCRuntimeConfig(Protocol):
    provider: str
    base_url: str
    speaker_id: int
    pitch: int
    timeout: float


class SummaryRuntimeConfig(Protocol):
    trigger_messages: int
    keep_recent_messages: int
    item_max_chars: int
    rewrite_interval_messages: int
    quality_scorer_mode: str
    quality_score_cooldown_seconds: int
    quality_score_budget_per_hour: int


class MemoryRuntimeConfig(Protocol):
    backend: str
    sqlite_path: str
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    qdrant_timeout: float
    qdrant_auto_start: bool
    qdrant_docker_image: str
    qdrant_docker_container: str
    qdrant_docker_volume: str
    embedding_model: str
    reranker_enabled: bool
    reranker_model: str
    reranker_candidate_count: int


class RuntimeConfig(Protocol):
    llm: LLMRuntimeConfig
    tts: TTSRuntimeConfig
    asr: ASRRuntimeConfig
    svc: SVCRuntimeConfig
    summary: SummaryRuntimeConfig
    memory: MemoryRuntimeConfig


class SummaryPolicyUpdater(Protocol):
    def update_summary_policy(
        self,
        *,
        trigger_messages: int,
        keep_recent_messages: int,
        item_max_chars: int,
        rewrite_interval_messages: int,
        quality_scorer_mode: str,
        quality_score_cooldown_seconds: int,
        quality_score_budget_per_hour: int,
    ) -> None: ...


class SocketServiceInjector(Protocol):
    def inject_services(
        self,
        *,
        llm_client: object | None,
        vision_llm_client: object | None,
        tts_client: object | None,
        asr_manager: object | None,
        generation_mgr: SummaryPolicyUpdater | None,
    ) -> None: ...


RuntimeUpdates = dict[str, object]
RuntimeSection = Mapping[str, object]
RuntimeLifecycleHook = Callable[[], Awaitable[object | None]]
RuntimeServiceProvider = Callable[[], object | None]


def _section(updates: RuntimeUpdates, key: str) -> RuntimeSection | None:
    value = updates.get(key)
    return cast(RuntimeSection, value) if isinstance(value, Mapping) else None


def _to_int(value: object) -> int:
    return int(str(value))


def _to_float(value: object) -> float:
    return float(str(value))


def apply_runtime_config(config: RuntimeConfig, updates: RuntimeUpdates) -> set[str]:
    changed: set[str] = set()

    llm_updates = _section(updates, "llm")
    if llm_updates is not None:
        provider = str(llm_updates.get("provider") or getattr(config.llm, "provider", "custom"))
        base_for_provider = str(llm_updates.get("base_url") or getattr(config.llm, "base_url", ""))
        if "provider" in llm_updates and llm_updates["provider"] is not None:
            config.llm.provider = normalize_llm_provider(llm_updates["provider"], base_for_provider)
            changed.add("llm")
        if "base_url" in llm_updates and llm_updates["base_url"] is not None:
            config.llm.base_url = normalize_llm_base_url(str(llm_updates["base_url"]), provider)
            changed.add("llm")
        if "api_key" in llm_updates and llm_updates["api_key"] is not None:
            config.llm.api_key = str(llm_updates["api_key"])
            changed.add("llm")
        if "model" in llm_updates and llm_updates["model"] is not None:
            config.llm.model = str(llm_updates["model"])
            changed.add("llm")
        if "timeout" in llm_updates and llm_updates["timeout"] is not None:
            config.llm.timeout = _to_float(llm_updates["timeout"])
            changed.add("llm")
        if "context_max_tokens" in llm_updates and llm_updates["context_max_tokens"] is not None:
            config.llm.context_max_tokens = _to_int(llm_updates["context_max_tokens"])
            changed.add("llm")
        if "default_max_output_tokens" in llm_updates and llm_updates["default_max_output_tokens"] is not None:
            config.llm.default_max_output_tokens = _to_int(llm_updates["default_max_output_tokens"])
            changed.add("llm")
        if "temperature" in llm_updates and llm_updates["temperature"] is not None:
            config.llm.temperature = _to_float(llm_updates["temperature"])
            changed.add("llm")
        if "top_p" in llm_updates and llm_updates["top_p"] is not None:
            config.llm.top_p = _to_float(llm_updates["top_p"])
            changed.add("llm")
        if "top_k" in llm_updates and llm_updates["top_k"] is not None:
            config.llm.top_k = _to_int(llm_updates["top_k"])
            changed.add("llm")
        if "min_p" in llm_updates and llm_updates["min_p"] is not None:
            config.llm.min_p = _to_float(llm_updates["min_p"])
            changed.add("llm")
        if "frequency_penalty" in llm_updates and llm_updates["frequency_penalty"] is not None:
            config.llm.frequency_penalty = _to_float(llm_updates["frequency_penalty"])
            changed.add("llm")
        if "presence_penalty" in llm_updates and llm_updates["presence_penalty"] is not None:
            config.llm.presence_penalty = _to_float(llm_updates["presence_penalty"])
            changed.add("llm")
        if "repetition_penalty" in llm_updates and llm_updates["repetition_penalty"] is not None:
            config.llm.repetition_penalty = _to_float(llm_updates["repetition_penalty"])
            changed.add("llm")
        vision_provider = str(llm_updates.get("vision_provider") or getattr(config.llm, "vision_provider", "custom"))
        vision_base = str(llm_updates.get("vision_base_url") or getattr(config.llm, "vision_base_url", ""))
        if "vision_enabled" in llm_updates and llm_updates["vision_enabled"] is not None:
            config.llm.vision_enabled = bool(llm_updates["vision_enabled"])
            changed.add("llm")
        if "vision_provider" in llm_updates and llm_updates["vision_provider"] is not None:
            config.llm.vision_provider = normalize_llm_provider(llm_updates["vision_provider"], vision_base)
            changed.add("llm")
        if "vision_base_url" in llm_updates and llm_updates["vision_base_url"] is not None:
            config.llm.vision_base_url = normalize_llm_base_url(str(llm_updates["vision_base_url"]), vision_provider)
            changed.add("llm")
        if "vision_api_key" in llm_updates and llm_updates["vision_api_key"] is not None:
            config.llm.vision_api_key = str(llm_updates["vision_api_key"])
            changed.add("llm")
        if "vision_model" in llm_updates and llm_updates["vision_model"] is not None:
            config.llm.vision_model = str(llm_updates["vision_model"]).strip()
            changed.add("llm")
        if "vision_timeout" in llm_updates and llm_updates["vision_timeout"] is not None:
            config.llm.vision_timeout = _to_float(llm_updates["vision_timeout"])
        if "vision_detail" in llm_updates and llm_updates["vision_detail"] is not None:
            detail = str(llm_updates["vision_detail"]).strip().lower()
            config.llm.vision_detail = detail if detail in {"low", "high", "auto", "original"} else "low"
            changed.add("llm")

    tts_updates = _section(updates, "tts")
    if tts_updates is not None:
        if "genie_character" in tts_updates and tts_updates["genie_character"] is not None:
            config.tts.genie_character = str(tts_updates["genie_character"]).strip()
            changed.add("tts")
        if "genie_model_dir" in tts_updates and tts_updates["genie_model_dir"] is not None:
            config.tts.genie_model_dir = str(tts_updates["genie_model_dir"]).strip()
            changed.add("tts")
        if "ref_audio" in tts_updates and tts_updates["ref_audio"] is not None:
            config.tts.ref_audio = str(tts_updates["ref_audio"])
            changed.add("tts")
        if "ref_text" in tts_updates and tts_updates["ref_text"] is not None:
            config.tts.ref_text = str(tts_updates["ref_text"])
            changed.add("tts")
        if "device" in tts_updates and tts_updates["device"] is not None:
            config.tts.device = str(tts_updates["device"]).strip().lower() or "cpu"
            changed.add("tts")
        if "quality" in tts_updates and tts_updates["quality"] is not None:
            config.tts.quality = str(tts_updates["quality"]).strip() or "质量优先"
            changed.add("tts")
        if "split" in tts_updates and tts_updates["split"] is not None:
            config.tts.split = str(tts_updates["split"]).strip() or "智能切分"
            changed.add("tts")
        if "mode" in tts_updates and tts_updates["mode"] is not None:
            config.tts.mode = str(tts_updates["mode"]).strip() or "串行推理"
            changed.add("tts")
        if "save_mode" in tts_updates and tts_updates["save_mode"] is not None:
            config.tts.save_mode = str(tts_updates["save_mode"]).strip() or "禁用自动保存"
            changed.add("tts")
        if "lang" in tts_updates and tts_updates["lang"] is not None:
            config.tts.lang = str(tts_updates["lang"])
            changed.add("tts")
        if "provider" in tts_updates and tts_updates["provider"] is not None:
            config.tts.provider = str(tts_updates["provider"])
            changed.add("tts")

    asr_updates = _section(updates, "asr")
    if asr_updates is not None:
        if "provider" in asr_updates and asr_updates["provider"] is not None:
            provider = str(asr_updates["provider"]).strip().lower() or "sherpa-onnx-online"
            config.asr.provider = provider
            changed.add("asr")
        if "base_url" in asr_updates and asr_updates["base_url"] is not None:
            config.asr.base_url = str(asr_updates["base_url"]).rstrip("/")
            changed.add("asr")
        if "api_key" in asr_updates and asr_updates["api_key"] is not None:
            config.asr.api_key = str(asr_updates["api_key"])
            changed.add("asr")
        if "timeout" in asr_updates and asr_updates["timeout"] is not None:
            config.asr.timeout = _to_float(asr_updates["timeout"])
            changed.add("asr")
        if "sensevoice_model" in asr_updates and asr_updates["sensevoice_model"] is not None:
            config.asr.sensevoice_model = str(asr_updates["sensevoice_model"]).strip() or "iic/SenseVoiceSmall"
            changed.add("asr")
        if "sensevoice_device" in asr_updates and asr_updates["sensevoice_device"] is not None:
            config.asr.sensevoice_device = str(asr_updates["sensevoice_device"]).strip().lower() or "cpu"
            changed.add("asr")
        if "sherpa_model_path" in asr_updates and asr_updates["sherpa_model_path"] is not None:
            config.asr.sherpa_model_path = str(asr_updates["sherpa_model_path"]).strip()
            changed.add("asr")
        if "sherpa_tokens_path" in asr_updates and asr_updates["sherpa_tokens_path"] is not None:
            config.asr.sherpa_tokens_path = str(asr_updates["sherpa_tokens_path"]).strip()
            changed.add("asr")
        if "sherpa_num_threads" in asr_updates and asr_updates["sherpa_num_threads"] is not None:
            config.asr.sherpa_num_threads = max(1, _to_int(asr_updates["sherpa_num_threads"]))
            changed.add("asr")
        if "sherpa_provider" in asr_updates and asr_updates["sherpa_provider"] is not None:
            config.asr.sherpa_provider = str(asr_updates["sherpa_provider"]).strip().lower() or "cpu"
            changed.add("asr")
        language = asr_updates.get("language")
        if language is not None:
            config.asr.language = str(language)
            changed.add("asr")
        if "vad_threshold" in asr_updates and asr_updates["vad_threshold"] is not None:
            config.asr.vad_threshold = max(0.1, min(0.9, _to_float(asr_updates["vad_threshold"])))
            changed.add("asr")
        if "vad_min_silence_ms" in asr_updates and asr_updates["vad_min_silence_ms"] is not None:
            config.asr.vad_min_silence_ms = max(160, min(1200, _to_int(asr_updates["vad_min_silence_ms"])))
            changed.add("asr")
        if "asr_partial_every" in asr_updates and asr_updates["asr_partial_every"] is not None:
            config.asr.asr_partial_every = max(1, min(30, _to_int(asr_updates["asr_partial_every"])))
            changed.add("asr")

    svc_updates = _section(updates, "svc")
    if svc_updates is not None:
        if "provider" in svc_updates and svc_updates["provider"] is not None:
            config.svc.provider = str(svc_updates["provider"]).strip().lower() or "soulx-service"
            changed.add("svc")
        if "base_url" in svc_updates and svc_updates["base_url"] is not None:
            config.svc.base_url = str(svc_updates["base_url"]).rstrip("/")
            changed.add("svc")
        if "speaker_id" in svc_updates and svc_updates["speaker_id"] is not None:
            config.svc.speaker_id = _to_int(svc_updates["speaker_id"])
            changed.add("svc")
        if "pitch" in svc_updates and svc_updates["pitch"] is not None:
            config.svc.pitch = _to_int(svc_updates["pitch"])
            changed.add("svc")
        if "timeout" in svc_updates and svc_updates["timeout"] is not None:
            config.svc.timeout = _to_float(svc_updates["timeout"])
            changed.add("svc")

    summary_updates = _section(updates, "summary")
    if summary_updates is not None:
        if "trigger_messages" in summary_updates and summary_updates["trigger_messages"] is not None:
            config.summary.trigger_messages = _to_int(summary_updates["trigger_messages"])
            changed.add("summary")
        if "keep_recent_messages" in summary_updates and summary_updates["keep_recent_messages"] is not None:
            config.summary.keep_recent_messages = _to_int(summary_updates["keep_recent_messages"])
            changed.add("summary")
        if "item_max_chars" in summary_updates and summary_updates["item_max_chars"] is not None:
            config.summary.item_max_chars = _to_int(summary_updates["item_max_chars"])
            changed.add("summary")
        if "rewrite_interval_messages" in summary_updates and summary_updates["rewrite_interval_messages"] is not None:
            config.summary.rewrite_interval_messages = _to_int(summary_updates["rewrite_interval_messages"])
            changed.add("summary")
        if "quality_scorer_mode" in summary_updates and summary_updates["quality_scorer_mode"] is not None:
            mode = str(summary_updates["quality_scorer_mode"]).strip().lower()
            config.summary.quality_scorer_mode = mode if mode in {"rule", "llm"} else "rule"
            changed.add("summary")
        if "quality_score_cooldown_seconds" in summary_updates and summary_updates["quality_score_cooldown_seconds"] is not None:
            config.summary.quality_score_cooldown_seconds = _to_int(summary_updates["quality_score_cooldown_seconds"])
            changed.add("summary")
        if "quality_score_budget_per_hour" in summary_updates and summary_updates["quality_score_budget_per_hour"] is not None:
            config.summary.quality_score_budget_per_hour = _to_int(summary_updates["quality_score_budget_per_hour"])
            changed.add("summary")

    memory_updates = _section(updates, "memory")
    if memory_updates is not None:
        if "backend" in memory_updates and memory_updates["backend"] is not None:
            config.memory.backend = str(memory_updates["backend"]).strip().lower()
            changed.add("memory")
        if "sqlite_path" in memory_updates and memory_updates["sqlite_path"] is not None:
            config.memory.sqlite_path = str(memory_updates["sqlite_path"]).strip()
            changed.add("memory")
        if "qdrant_url" in memory_updates and memory_updates["qdrant_url"] is not None:
            config.memory.qdrant_url = str(memory_updates["qdrant_url"]).rstrip("/")
            changed.add("memory")
        if "qdrant_api_key" in memory_updates and memory_updates["qdrant_api_key"] is not None:
            config.memory.qdrant_api_key = str(memory_updates["qdrant_api_key"]).strip()
            changed.add("memory")
        if "qdrant_collection" in memory_updates and memory_updates["qdrant_collection"] is not None:
            config.memory.qdrant_collection = str(memory_updates["qdrant_collection"]).strip() or "memories"
            changed.add("memory")
        if "qdrant_timeout" in memory_updates and memory_updates["qdrant_timeout"] is not None:
            config.memory.qdrant_timeout = _to_float(memory_updates["qdrant_timeout"])
            changed.add("memory")
        if "qdrant_auto_start" in memory_updates and memory_updates["qdrant_auto_start"] is not None:
            config.memory.qdrant_auto_start = bool(memory_updates["qdrant_auto_start"])
            changed.add("memory")
        if "qdrant_docker_image" in memory_updates and memory_updates["qdrant_docker_image"] is not None:
            config.memory.qdrant_docker_image = str(memory_updates["qdrant_docker_image"]).strip() or DEFAULT_QDRANT_DOCKER_IMAGE
            changed.add("memory")
        if "qdrant_docker_container" in memory_updates and memory_updates["qdrant_docker_container"] is not None:
            config.memory.qdrant_docker_container = str(memory_updates["qdrant_docker_container"]).strip() or DEFAULT_QDRANT_DOCKER_CONTAINER
            changed.add("memory")
        if "qdrant_docker_volume" in memory_updates and memory_updates["qdrant_docker_volume"] is not None:
            config.memory.qdrant_docker_volume = str(memory_updates["qdrant_docker_volume"]).strip() or DEFAULT_QDRANT_DOCKER_VOLUME
            changed.add("memory")
        if "embedding_model" in memory_updates and memory_updates["embedding_model"] is not None:
            config.memory.embedding_model = str(memory_updates["embedding_model"]).strip() or DEFAULT_EMBEDDING_MODEL
            changed.add("memory")
        if "reranker_enabled" in memory_updates and memory_updates["reranker_enabled"] is not None:
            config.memory.reranker_enabled = bool(memory_updates["reranker_enabled"])
            changed.add("memory")
        if "reranker_model" in memory_updates and memory_updates["reranker_model"] is not None:
            config.memory.reranker_model = str(memory_updates["reranker_model"]).strip() or "BAAI/bge-reranker-v2-m3"
            changed.add("memory")
        if "reranker_candidate_count" in memory_updates and memory_updates["reranker_candidate_count"] is not None:
            config.memory.reranker_candidate_count = max(5, min(100, _to_int(memory_updates["reranker_candidate_count"])))
            changed.add("memory")

    return changed


async def reload_runtime_services(
    changed: set[str],
    config: RuntimeConfig,
    generation_mgr: SummaryPolicyUpdater | None,
    sio_server: SocketServiceInjector,
    llm_client: object | None,
    tts_client: object | None,
    asr_manager: object | None,
    init_llm: RuntimeLifecycleHook,
    cleanup_llm: RuntimeLifecycleHook,
    init_tts: RuntimeLifecycleHook,
    cleanup_tts: RuntimeLifecycleHook,
    init_svc: RuntimeLifecycleHook,
    cleanup_svc: RuntimeLifecycleHook,
    init_asr: RuntimeLifecycleHook,
    cleanup_asr: RuntimeLifecycleHook,
    llm_client_provider: RuntimeServiceProvider | None = None,
    tts_client_provider: RuntimeServiceProvider | None = None,
    asr_manager_provider: RuntimeServiceProvider | None = None,
    vision_llm_client_provider: RuntimeServiceProvider | None = None,
) -> None:
    if "llm" in changed:
        _ = await cleanup_llm()
        _ = await init_llm()

    if "tts" in changed:
        _ = await cleanup_tts()
        _ = await init_tts()

    if "svc" in changed:
        _ = await cleanup_svc()
        _ = await init_svc()

    if "asr" in changed:
        _ = await cleanup_asr()
        _ = await init_asr()

    if "summary" in changed and generation_mgr is not None:
        generation_mgr.update_summary_policy(
            trigger_messages=config.summary.trigger_messages,
            keep_recent_messages=config.summary.keep_recent_messages,
            item_max_chars=config.summary.item_max_chars,
            rewrite_interval_messages=config.summary.rewrite_interval_messages,
            quality_scorer_mode=config.summary.quality_scorer_mode,
            quality_score_cooldown_seconds=config.summary.quality_score_cooldown_seconds,
            quality_score_budget_per_hour=config.summary.quality_score_budget_per_hour,
        )

    if changed.intersection({"llm", "tts", "asr"}):
        sio_server.inject_services(
            llm_client=llm_client_provider() if llm_client_provider is not None else llm_client,
            vision_llm_client=vision_llm_client_provider() if vision_llm_client_provider is not None else None,
            tts_client=tts_client_provider() if tts_client_provider is not None else tts_client,
            asr_manager=asr_manager_provider() if asr_manager_provider is not None else asr_manager,
            generation_mgr=generation_mgr,
        )

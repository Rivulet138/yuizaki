from __future__ import annotations

import logging
import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from ..asr import ASRManager
from ..llm import LLMClient
from ..ocr import OCRClient
from ..svc import SVCClient
from ..tts import TTSClient


class LLMServiceConfig(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def base_url(self) -> str: ...
    @property
    def api_key(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def timeout(self) -> float: ...
    @property
    def vision_enabled(self) -> bool: ...
    @property
    def vision_provider(self) -> str: ...
    @property
    def vision_base_url(self) -> str: ...
    @property
    def vision_api_key(self) -> str: ...
    @property
    def vision_model(self) -> str: ...
    @property
    def vision_timeout(self) -> float: ...
    @property
    def vision_detail(self) -> str: ...


class TTSServiceConfig(Protocol):
    @property
    def genie_character(self) -> str: ...
    @property
    def genie_model_dir(self) -> str: ...
    @property
    def language(self) -> str: ...
    @property
    def lang(self) -> str: ...
    @property
    def ref_audio(self) -> str: ...
    @property
    def ref_text(self) -> str: ...
    @property
    def device(self) -> str: ...
    @property
    def quality(self) -> str: ...
    @property
    def split(self) -> str: ...
    @property
    def mode(self) -> str: ...
    @property
    def save_mode(self) -> str: ...
    @property
    def audio_cache_dir(self) -> Path: ...


class ASRServiceConfig(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def base_url(self) -> str: ...
    @property
    def api_key(self) -> str: ...
    @property
    def timeout(self) -> float: ...
    @property
    def sensevoice_model(self) -> str: ...
    @property
    def sensevoice_device(self) -> str: ...
    @property
    def sherpa_model_path(self) -> str: ...
    @property
    def sherpa_tokens_path(self) -> str: ...
    @property
    def sherpa_num_threads(self) -> int: ...
    @property
    def sherpa_provider(self) -> str: ...
    @property
    def vad_threshold(self) -> float: ...
    @property
    def vad_min_silence_ms(self) -> int: ...
    @property
    def asr_partial_every(self) -> int: ...
    @property
    def language(self) -> str: ...


class SVCServiceConfig(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def base_url(self) -> str: ...
    @property
    def speaker_id(self) -> int: ...
    @property
    def pitch(self) -> int: ...
    @property
    def timeout(self) -> float: ...


class ServiceConfig(Protocol):
    @property
    def llm(self) -> LLMServiceConfig: ...
    @property
    def tts(self) -> TTSServiceConfig: ...
    @property
    def asr(self) -> ASRServiceConfig: ...
    @property
    def svc(self) -> SVCServiceConfig: ...


class SenseVoiceRuntimeClient(Protocol):
    async def disconnect(self) -> None: ...


class RuntimeContextInjector(Protocol):
    def inject_runtime_context(
        self,
        *,
        db_repo: object,
        relationship_event_writer: object,
        relationship_history_provider: object,
        relationship_summary_provider: object,
    ) -> None: ...


class DatabaseRepositoryFactory(Protocol):
    def __call__(self) -> object: ...


RelationshipMemoryWriter = Callable[[dict[str, object]], object | None]
RelationshipHistoryProvider = Callable[[], object]
RelationshipSummaryProvider = Callable[[], object]


def _database_repository_factory() -> DatabaseRepositoryFactory:
    database_module = importlib.import_module("database")
    repository_factory = cast(object, getattr(database_module, "DatabaseRepository"))
    return cast(DatabaseRepositoryFactory, repository_factory)


async def initialize_llm(service_config: ServiceConfig, logger: logging.Logger) -> LLMClient:
    client = LLMClient(
        service_config.llm.base_url,
        service_config.llm.api_key,
        service_config.llm.model,
        service_config.llm.timeout,
        provider=service_config.llm.provider,
    )
    await client.connect()
    logger.info("LLM client initialized")
    return client


async def initialize_vision_llm(service_config: ServiceConfig, logger: logging.Logger) -> LLMClient | None:
    llm = service_config.llm
    if not llm.vision_enabled or not llm.vision_base_url.strip() or not llm.vision_model.strip():
        logger.info("Dedicated vision LLM disabled or incomplete")
        return None
    client = LLMClient(
        llm.vision_base_url,
        llm.vision_api_key,
        llm.vision_model,
        llm.vision_timeout,
        provider=llm.vision_provider,
        image_detail=llm.vision_detail,
    )
    await client.connect()
    logger.info("Vision LLM client initialized (provider=%s, model=%s)", llm.vision_provider, llm.vision_model)
    return client


async def cleanup_llm(client: LLMClient | None) -> None:
    if client is not None:
        await client.disconnect()


async def initialize_tts(service_config: ServiceConfig, logger: logging.Logger) -> TTSClient:
    client = TTSClient(
        genie_character=service_config.tts.genie_character,
        genie_model_dir=service_config.tts.genie_model_dir or None,
            language=service_config.tts.lang,
        ref_audio=service_config.tts.ref_audio,
        ref_text=service_config.tts.ref_text,
        device=service_config.tts.device,
        quality=service_config.tts.quality,
        split=service_config.tts.split,
        mode=service_config.tts.mode,
        save_mode=service_config.tts.save_mode,
        audio_cache_dir=service_config.tts.audio_cache_dir,
    )
    startup_mode = _tts_startup_mode()
    warmup_enabled = _tts_warmup_enabled()
    if startup_mode == "blocking":
        await client.connect()
        if warmup_enabled:
            await client.warmup()
    elif startup_mode == "background":
        await client.connect(background=True)
        if warmup_enabled:
            await client.warmup(background=True)
    if client.is_enabled:
        logger.info("TTS client initialized (Genie-TTS, character=%s)", service_config.tts.genie_character)
    elif client.is_warming_up:
        logger.info("TTS client warming in background (Genie-TTS, character=%s)", service_config.tts.genie_character)
    elif startup_mode == "lazy":
        logger.info("TTS client configured for lazy loading (Genie-TTS, character=%s)", service_config.tts.genie_character)
    else:
        logger.warning("TTS client not available; genie-tts may not be installed")
    return client


async def cleanup_tts(client: TTSClient | None) -> None:
    if client is not None:
        await client.disconnect()


def _tts_startup_mode() -> str:
    mode = os.getenv("TTS_STARTUP_MODE", "background").strip().lower()
    if mode in {"blocking", "eager", "foreground", "sync"}:
        return "blocking"
    if mode in {"background", "warmup", "preload"}:
        return "background"
    return "lazy"


def _tts_warmup_enabled() -> bool:
    value = os.getenv("TTS_WARMUP_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


async def initialize_asr(service_config: ServiceConfig, logger: logging.Logger) -> ASRManager | None:
    try:
        from ..asr.sensevoice import (
            SenseVoiceClient,
            SenseVoiceServiceClient,
            SherpaOnnxOnlineClient,
            SherpaOnnxSenseVoiceClient,
        )

        provider = service_config.asr.provider.strip().lower()
        if provider in {"disabled", "none", "off"}:
            logger.info("ASR disabled by provider=%s", provider)
            return None

        if provider in {"sensevoice-service", "funasr-service", "openai-compatible"}:
            sensevoice_client = SenseVoiceServiceClient(
                model=service_config.asr.sensevoice_model,
                base_url=service_config.asr.base_url,
                api_key=service_config.asr.api_key,
                timeout=service_config.asr.timeout,
            )
        elif provider == "sherpa-onnx-online":
            sensevoice_client = SherpaOnnxOnlineClient(
                model_path=service_config.asr.sherpa_model_path,
                tokens_path=service_config.asr.sherpa_tokens_path,
                num_threads=service_config.asr.sherpa_num_threads,
                provider=service_config.asr.sherpa_provider,
                language=service_config.asr.language,
            )
        elif provider == "sherpa-onnx":
            sensevoice_client = SherpaOnnxSenseVoiceClient(
                model_path=service_config.asr.sherpa_model_path,
                tokens_path=service_config.asr.sherpa_tokens_path,
                num_threads=service_config.asr.sherpa_num_threads,
                provider=service_config.asr.sherpa_provider,
                language=service_config.asr.language,
            )
        else:
            sensevoice_client = SenseVoiceClient(
                model=service_config.asr.sensevoice_model,
                device=service_config.asr.sensevoice_device,
            )
        await sensevoice_client.connect()
        if not sensevoice_client.is_available:
            logger.info("ASR client not available; voice input disabled")
            return None

        manager = ASRManager(
            sensevoice_client,
            service_config.asr.vad_threshold,
            service_config.asr.vad_min_silence_ms,
            service_config.asr.asr_partial_every,
            service_config.asr.language,
        )
        logger.info("ASR manager initialized (provider=%s)", provider or "sensevoice-local")
        return manager
    except ImportError:
        logger.warning("ASR dependencies not available")
    except Exception:
        logger.exception("ASR init failed; continuing without ASR")
    return None


async def cleanup_asr(manager: ASRManager | None) -> None:
    if manager is None:
        return
    sensevoice_client = cast(SenseVoiceRuntimeClient | None, getattr(manager, "sensevoice_client", None))
    if sensevoice_client is not None:
        await sensevoice_client.disconnect()


async def initialize_svc(service_config: ServiceConfig, logger: logging.Logger) -> SVCClient:
    client = SVCClient(
        provider=service_config.svc.provider,
        base_url=service_config.svc.base_url,
        speaker_id=service_config.svc.speaker_id,
        pitch=service_config.svc.pitch,
        timeout=service_config.svc.timeout,
        audio_cache_dir=service_config.tts.audio_cache_dir,
    )
    await client.connect()
    if client.is_available:
        logger.info("SVC client initialized")
    else:
        logger.info("SVC client not available; voice conversion disabled")
    return client


async def cleanup_svc(client: SVCClient | None) -> None:
    if client is not None:
        await client.disconnect()


async def initialize_ocr(logger: logging.Logger) -> OCRClient:
    client = OCRClient()
    logger.info("OCR client registered for on-demand initialization")
    return client


async def cleanup_ocr(client: OCRClient | None) -> None:
    if client is not None:
        await client.disconnect()


def initialize_database(
    sio_server: object,
    relationship_event_writer: RelationshipMemoryWriter,
    relationship_history_provider: RelationshipHistoryProvider,
    relationship_summary_provider: RelationshipSummaryProvider,
    logger: logging.Logger,
) -> object:
    repository = _database_repository_factory()()
    runtime_context_injector = cast(RuntimeContextInjector, sio_server)
    runtime_context_injector.inject_runtime_context(
        db_repo=repository,
        relationship_event_writer=relationship_event_writer,
        relationship_history_provider=relationship_history_provider,
        relationship_summary_provider=relationship_summary_provider,
    )
    logger.info("Database initialized")
    return repository

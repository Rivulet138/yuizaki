"""Yuizaki Backend - Modularized FastAPI Application with System Architecture, Database & Socket.IO"""
import asyncio
import importlib
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, cast
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from modules.core import config, GenerationManager, public_config_snapshot
from modules.core.paths import DEFAULT_RUNTIME_TEMP_DIR, data_dir_from_env, settings_path_from_env
from modules.core.settings import SettingsManager
from modules.llm import LLMClient
from modules.tts import TTSClient
from modules.asr import ASRManager
from modules.svc import SVCClient
from modules.ocr import OCRClient
from modules.system import (
    DynamicConfigManager,
    HealthChecker,
    ServiceManager,
    SlidingWindowRateLimiter,
)
from modules.system.settings_api import SettingsAPI
import modules.system.runtime_config as system_runtime_config
from modules.system.active_workspace_state import ActiveWorkspaceState
from modules.system.active_application import read_active_application
from modules.system.backend_api_auth import (
    HOST_DESKTOP_ACTION_PREFIX,
    HOST_DESKTOP_ACTION_TOKEN_ENV,
    backend_api_auth_required,
    verify_backend_api_authorization,
    verify_host_desktop_action_authorization,
)
from modules.system.cache_janitor import run_audio_cache_janitor
from modules.system.companion_runtime import build_companion_runtime_snapshot
from modules.system.governance_alert_state import GovernanceAlertStateStore
from modules.system.memory_query import build_memory_query_request
from modules.system.runtime_endpoints import build_companion_runtime_endpoint
from modules.system.message_connectors import MessageConnectorRegistry
from modules.system.schema_policy import enforce_schema_policy
import modules.system.runtime_composition as system_runtime_composition
from modules.system.runtime_composition import build_runtime_handlers
from evals.product_metrics import JsonProductConsentStateStore
from modules.system.relationship_runtime import (
    build_companion_relationship_history_endpoint,
    build_relationship_memory_writer,
    build_recent_relationship_history_provider,
    build_relationship_summary_provider,
)
from socket_server import DesktopPetSocketServer, _parse_socket_allowed_origins
from database import DatabaseRepository
from routes.ai_api import create_ai_router
from routes.database_api import create_database_router
from routes.i18n import router as i18n_router
from routes.summary_api import create_summary_router
from routes.system_api import create_system_router
from routes.workspace_api import create_workspace_router
from routes.companion_api import create_companion_router
from routes.realtime_api import create_realtime_router
from routes.connector_api import create_message_connector_router
from routes.storage_api import create_storage_router
from modules.system.settings_api import router as settings_router
from modules.system.logging_config import configure_application_logging
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.backend_factory import create_memory_backend
from modules.system.heartbeat import HeartbeatScheduler, DEFAULT_HEARTBEAT_INTERVAL_SECONDS
from modules.system.heartbeat_goal_store import HeartbeatGoalStore
from modules.system.health_providers import build_app_runtime_health_providers, register_app_runtime_health_checks
from modules.system.onboarding_readiness import OnboardingReadiness
from modules.system.runtime_services import voice_diagnostics
from modules.system.ui_capabilities import build_ui_capabilities
from modules.system.stream_platforms import InMemoryTwitchSubscriptionProvider, TwitchHelixSubscriptionProvider
from modules.system.stream_runtime import ObsWebSocketAdapter, StreamRuntime
from modules.system.runtime_config import RuntimeConfig, apply_runtime_config
from modules.system.settings_schema import validate_runtime_patch

LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"


def _configure_logging() -> None:
    default_log_file = Path(__file__).resolve().parents[1] / "logs" / "dev" / "python.log"
    configure_application_logging(default_log_file, LOG_FORMAT)


_configure_logging()
logger = logging.getLogger("yuizaki")


class RuntimeServicesModule(Protocol):
    def initialize_llm(self, service_config: object, logger: logging.Logger) -> Awaitable[LLMClient]: ...
    def initialize_vision_llm(
        self,
        service_config: object,
        logger: logging.Logger,
    ) -> Awaitable[LLMClient | None]: ...
    def cleanup_llm(self, client: LLMClient | None) -> Awaitable[None]: ...
    def initialize_tts(self, service_config: object, logger: logging.Logger) -> Awaitable[TTSClient]: ...
    def cleanup_tts(self, client: TTSClient | None) -> Awaitable[None]: ...
    def initialize_asr(self, service_config: object, logger: logging.Logger) -> Awaitable[ASRManager | None]: ...
    def cleanup_asr(self, manager: ASRManager | None) -> Awaitable[None]: ...
    def initialize_svc(self, service_config: object, logger: logging.Logger) -> Awaitable[SVCClient]: ...
    def cleanup_svc(self, client: SVCClient | None) -> Awaitable[None]: ...
    def initialize_ocr(self, logger: logging.Logger) -> Awaitable[OCRClient]: ...
    def cleanup_ocr(self, client: OCRClient | None) -> Awaitable[None]: ...
    def initialize_database(
        self,
        sio_server: object,
        relationship_event_writer: object,
        relationship_history_provider: object,
        relationship_summary_provider: object,
        logger: logging.Logger,
    ) -> DatabaseRepository: ...


def _runtime_services() -> RuntimeServicesModule:
    module = cast(object, importlib.import_module("modules.system.runtime_services"))
    return cast(RuntimeServicesModule, module)


def _parse_allowed_origins(value: str | None) -> list[str]:
    return _parse_socket_allowed_origins(value)


def _parse_port(value: str | None, fallback: int) -> int:
    try:
        port = int(str(value or "").strip())
    except ValueError:
        return fallback
    return port if 0 < port <= 65535 else fallback


for _env_key in ("HF_HOME", "SENTENCE_TRANSFORMERS_HOME", "EMBEDDING_MODEL_LOCAL_PATH", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    _env_val = os.getenv(_env_key)
    if _env_val is not None:
        os.environ[_env_key] = _env_val.strip()

_default_hf_home = Path(".cache") / "huggingface"
if not os.getenv("HF_HOME") and _default_hf_home.exists():
    os.environ["HF_HOME"] = str(_default_hf_home)

# System components
service_manager = ServiceManager()
health_checker = HealthChecker()
settings_api = None  # Settings API instance
settings_manager: SettingsManager | None = None
db_repo: DatabaseRepository | None = None  # 数据库实例
_active_workspace_state = ActiveWorkspaceState()
_message_connector_registry = MessageConnectorRegistry(state_path=data_dir_from_env() / "message_connectors.json")
_connector_recovery_controller = None

_llm_client: LLMClient | None = None
_vision_llm_client: LLMClient | None = None
_tts_client: TTSClient | None = None
_asr_manager: ASRManager | None = None
_svc_client: SVCClient | None = None
_ocr_client: OCRClient | None = None
_generation_mgr: GenerationManager | None = None
_janitor_task: asyncio.Task[None] | None = None
_retrieval_pipeline = None
_heartbeat_scheduler = None
_memory_state = None
_memory_reload_lock = asyncio.Lock()
_summary_list_limiter = SlidingWindowRateLimiter(max_requests=20, window_seconds=10.0)
_summary_detail_limiter = SlidingWindowRateLimiter(max_requests=30, window_seconds=10.0)
_summary_rewrite_limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=30.0)
_governance_alert_store = GovernanceAlertStateStore(data_dir_from_env() / "governance_alert_state.json", logger)
_product_metrics_consent_store = JsonProductConsentStateStore(data_dir_from_env() / "product_metrics_consent.json")


def _apply_persisted_memory_config_before_backend_init() -> None:
    """Apply persisted memory settings before module-level memory routes are built."""
    settings_path = settings_path_from_env()
    if not settings_path.exists():
        return
    try:
        with open(settings_path, "r", encoding="utf-8") as settings_file:
            loaded = json.load(settings_file)
        if not isinstance(loaded, dict):
            return
        memory_payload = loaded.get("memory")
        if not isinstance(memory_payload, dict):
            return
        runtime_updates = validate_runtime_patch({"memory": memory_payload}).model_dump(exclude_none=True, exclude_unset=True)
        apply_runtime_config(cast(RuntimeConfig, config), runtime_updates)
        logger.info("Applied persisted memory settings before memory backend initialization")
    except Exception as exc:
        logger.warning("Failed to apply persisted memory settings before backend init: %s", exc)


def _get_active_workspace_id() -> str:
    return _active_workspace_state.get()


def _get_memory_store():
    if _memory_state is None:
        raise RuntimeError("memory_store_not_initialized")
    return _memory_state.store


async def _reload_memory_runtime() -> None:
    """Atomically swap a fully hydrated memory backend after settings change."""
    global _retrieval_pipeline
    async with _memory_reload_lock:
        if _memory_state is None:
            return
        previous_store = _memory_state.store
        previous_docs = await asyncio.to_thread(previous_store.list_documents)
        new_store = create_memory_backend(config.memory)
        try:
            for doc in previous_docs:
                await asyncio.to_thread(new_store.add_document, doc)
            await asyncio.to_thread(new_store.list_documents)
            new_pipeline = RetrievalPipeline(new_store)
        except Exception:
            logger.exception("Memory backend reload failed; retaining current authority")
            return

        _memory_state.store = new_store
        _retrieval_pipeline = new_pipeline
        _memory_state.pipeline = new_pipeline
        sio_server.runtime.agent_pipeline.bind_retrieval_pipeline(new_pipeline)
        logger.info(
            "Memory runtime atomically reloaded (backend=%s, preserved_docs=%d)",
            getattr(new_store, "backend_name", "unknown"),
            len(previous_docs),
        )

# Socket.IO 服务器实例
sio_server = DesktopPetSocketServer()

async def _init_llm():
    """Initialize LLM service."""
    global _llm_client, _vision_llm_client
    _llm_client = await _runtime_services().initialize_llm(config, logger)
    try:
        _vision_llm_client = await _runtime_services().initialize_vision_llm(config, logger)
    except Exception as exc:
        _vision_llm_client = None
        logger.warning("Vision LLM initialization failed; realtime visual analysis is unavailable: %s", exc)

async def _cleanup_llm():
    """Cleanup LLM service."""
    global _llm_client, _vision_llm_client
    await _runtime_services().cleanup_llm(_vision_llm_client)
    await _runtime_services().cleanup_llm(_llm_client)
    _vision_llm_client = None
    _llm_client = None

async def _init_tts():
    """Initialize TTS service using Genie-TTS."""
    global _tts_client
    _tts_client = await _runtime_services().initialize_tts(config, logger)

async def _cleanup_tts():
    """Cleanup TTS service."""
    global _tts_client
    await _runtime_services().cleanup_tts(_tts_client)
    _tts_client = None

async def _init_asr():
    """Initialize ASR service using SenseVoiceSmall."""
    global _asr_manager
    _asr_manager = await _runtime_services().initialize_asr(config, logger)

async def _cleanup_asr():
    global _asr_manager
    await _runtime_services().cleanup_asr(_asr_manager)
    _asr_manager = None

async def _init_svc():
    """Initialize optional SVC service."""
    global _svc_client
    _svc_client = await _runtime_services().initialize_svc(config, logger)

async def _cleanup_svc():
    """Cleanup SVC service."""
    global _svc_client
    await _runtime_services().cleanup_svc(_svc_client)
    _svc_client = None

async def _init_ocr():
    """Initialize OCR service."""
    global _ocr_client
    _ocr_client = await _runtime_services().initialize_ocr(logger)

async def _cleanup_ocr():
    """Cleanup OCR service."""
    global _ocr_client
    await _runtime_services().cleanup_ocr(_ocr_client)
    _ocr_client = None

async def _init_generation_manager():
    """Initialize generation manager."""
    global _generation_mgr
    _generation_mgr = GenerationManager()
    logger.info("Generation manager initialized")

async def _init_database():
    """Initialize database."""
    global db_repo
    db_repo = _runtime_services().initialize_database(
        sio_server,
        _write_relationship_memory,
        _recent_relationship_history,
        _relationship_evolution_summary,
        logger,
    )

@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    global _llm_client, _vision_llm_client, _tts_client, _asr_manager, _svc_client, _ocr_client, _generation_mgr, _janitor_task, db_repo, settings_api, settings_manager, _retrieval_pipeline, _heartbeat_scheduler, _connector_recovery_controller
    logger.info("Starting Yuizaki backend...")
    enforce_schema_policy()

    # Initialize settings system
    from modules.system.settings_store import SettingsStore

    settings_store = SettingsStore()
    dynamic_config = DynamicConfigManager()
    async def _reload_runtime_for_settings(changed: set[str]) -> None:
        if "memory" in changed:
            await _reload_memory_runtime()
        reload_runtime_services = getattr(system_runtime_config, "reload_runtime_services")
        await reload_runtime_services(
            changed,
            config,
            _generation_mgr,
            sio_server,
            _llm_client,
            _tts_client,
            _asr_manager,
            _init_llm,
            _cleanup_llm,
            _init_tts,
            _cleanup_tts,
            _init_svc,
            _cleanup_svc,
            _init_asr,
            _cleanup_asr,
            lambda: _llm_client,
            lambda: _tts_client,
            lambda: _asr_manager,
            lambda: _vision_llm_client,
            lambda: _svc_client,
            lambda: _ocr_client,
        )

    settings_api = SettingsAPI(settings_store, dynamic_config, config=config, reload_runtime_services=_reload_runtime_for_settings)
    settings_api.set_client_providers(lambda: _llm_client, lambda: _tts_client)
    settings_api.init_api()
    # High-level typed settings manager backed by the same store
    settings_manager = SettingsManager()
    # Register services
    service_manager.register("generation_manager", _init_generation_manager)
    service_manager.register("database", _init_database)
    service_manager.register("llm", _init_llm, _cleanup_llm, depends_on=["generation_manager"])
    service_manager.register("tts", _init_tts, _cleanup_tts)
    service_manager.register("asr", _init_asr, _cleanup_asr)
    service_manager.register("svc", _init_svc, _cleanup_svc)
    service_manager.register("ocr", _init_ocr, _cleanup_ocr)

    # Register health checks
    register_app_runtime_health_checks(health_checker, runtime_health_providers)

    # Start all services
    if not await service_manager.start_all():
        logger.error("Failed to start all services")
        raise RuntimeError("Service startup failed")

    _governance_alert_store.load()
    _heartbeat_scheduler = HeartbeatScheduler(
        interval_seconds=DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        trace_provider=lambda: _retrieval_pipeline.last_trace if _retrieval_pipeline else None,
        companion_provider=lambda: db_repo.get_workspace_companion(_get_active_workspace_id()) if db_repo else None,
        companion_persist=lambda companion_id, updates: db_repo.update_companion(companion_id, updates) if db_repo else None,
        relationship_memory_writer=lambda payload: _write_relationship_memory(payload),
        relationship_history_provider=lambda: _recent_relationship_history(),
        relationship_summary_provider=lambda: _relationship_evolution_summary(),
        workspace_id_provider=_get_active_workspace_id,
        job_event_log=sio_server.job_events,
        goal_store=HeartbeatGoalStore(),
    )
    if sio_server.runtime.activity_frame_service is not None:
        sio_server.runtime.activity_frame_service.bind_scheduler(_heartbeat_scheduler)
    await _heartbeat_scheduler.start()

    # Start cache janitor
    _janitor_task = asyncio.create_task(run_audio_cache_janitor(config.cache, config.tts, logger))
    logger.info("Backend startup complete")

    # Inject services into Socket.IO server
    sio_server.inject_services(
        llm_client=_llm_client,
        vision_llm_client=_vision_llm_client,
        tts_client=_tts_client,
        asr_manager=_asr_manager,
        svc_client=_svc_client,
        generation_mgr=_generation_mgr,
        ocr_client=_ocr_client,
    )
    sio_server.inject_runtime_context(
        db_repo=db_repo,
        relationship_event_writer=_write_relationship_memory,
        relationship_history_provider=_recent_relationship_history,
        relationship_summary_provider=_relationship_evolution_summary,
        active_workspace_provider=_get_active_workspace_id,
    )
    if sio_server.runtime.turn_outbox_worker is not None:
        await sio_server.runtime.turn_outbox_worker.start()
    if _connector_recovery_controller is not None:
        await _connector_recovery_controller.start()
    await runtime_handlers.stream_draft_consumer_start()
    logger.info("Socket.IO server ready")

    yield

    logger.info("Shutting down Yuizaki backend...")
    if _heartbeat_scheduler:
        await _heartbeat_scheduler.stop()
    if sio_server.runtime.turn_outbox_worker is not None:
        await sio_server.runtime.turn_outbox_worker.stop()
    if _connector_recovery_controller is not None:
        await _connector_recovery_controller.stop()
    await runtime_handlers.stream_draft_consumer_stop()
    _stream_runtime.shutdown()
    if _janitor_task:
        _janitor_task.cancel()
        try:
            await _janitor_task
        except asyncio.CancelledError:
            pass
    await sio_server.mcp_manager.shutdown()
    await service_manager.stop_all()
    if db_repo:
        db_repo.close()
    logger.info("Backend shutdown complete")

app = FastAPI(title="yuizaki", lifespan=app_lifespan)
_twitch_subscription_provider_mode = os.getenv("YUIZAKI_TWITCH_SUBSCRIPTION_PROVIDER", "").strip().lower()
_twitch_subscription_provider = None
if _twitch_subscription_provider_mode == "in-memory-staging":
    _twitch_subscription_provider = InMemoryTwitchSubscriptionProvider()
elif _twitch_subscription_provider_mode == "helix":
    _candidate_provider = TwitchHelixSubscriptionProvider(
        client_id=os.getenv("YUIZAKI_TWITCH_CLIENT_ID"),
        access_token=os.getenv("YUIZAKI_TWITCH_EVENTSUB_TOKEN") or os.getenv("YUIZAKI_TWITCH_CHAT_TOKEN"),
        broadcaster_id=os.getenv("YUIZAKI_TWITCH_BROADCASTER_ID"),
        callback_url=os.getenv("YUIZAKI_TWITCH_EVENTSUB_CALLBACK_URL"),
        secret=os.getenv("YUIZAKI_TWITCH_EVENTSUB_SECRET"),
        moderator_id=os.getenv("YUIZAKI_TWITCH_MODERATOR_ID"),
    )
    if _candidate_provider.configured:
        _twitch_subscription_provider = _candidate_provider

_stream_runtime = StreamRuntime(
    ObsWebSocketAdapter(
        os.getenv("YUIZAKI_OBS_WEBSOCKET_URL"),
        os.getenv("YUIZAKI_OBS_WEBSOCKET_PASSWORD"),
    ),
    twitch_eventsub_secret=os.getenv("YUIZAKI_TWITCH_EVENTSUB_SECRET"),
    twitch_client_id=os.getenv("YUIZAKI_TWITCH_CLIENT_ID"),
    twitch_eventsub_token=os.getenv("YUIZAKI_TWITCH_EVENTSUB_TOKEN"),
    twitch_chat_token=os.getenv("YUIZAKI_TWITCH_CHAT_TOKEN"),
    twitch_broadcaster_id=os.getenv("YUIZAKI_TWITCH_BROADCASTER_ID"),
    twitch_sender_id=os.getenv("YUIZAKI_TWITCH_SENDER_ID"),
    twitch_moderator_id=os.getenv("YUIZAKI_TWITCH_MODERATOR_ID"),
    twitch_channel=os.getenv("YUIZAKI_TWITCH_CHANNEL"),
    twitch_username=os.getenv("YUIZAKI_TWITCH_USERNAME"),
    twitch_eventsub_callback_url=os.getenv("YUIZAKI_TWITCH_EVENTSUB_CALLBACK_URL"),
    twitch_subscription_provider=_twitch_subscription_provider,
    events_path=data_dir_from_env() / "stream_events.json",
)

_BACKEND_API_TOKEN = os.getenv("YUIZAKI_BACKEND_API_TOKEN", "").strip()


@app.get("/api/ping")
async def ping():
    payload: dict[str, Any] = {"ok": True}
    instance_id = os.getenv("YUIZAKI_RUNTIME_INSTANCE_ID", "").strip()
    generation = os.getenv("YUIZAKI_RUNTIME_GENERATION", "").strip()
    startup_nonce = os.getenv("YUIZAKI_RUNTIME_STARTUP_NONCE", "").strip()
    if instance_id and generation and startup_nonce:
        payload["runtime"] = {
            "instance_id": instance_id,
            "generation": generation,
            "startup_nonce": startup_nonce,
            "pid": os.getpid(),
        }
    return payload


@app.get("/api/system/ui-capabilities")
async def ui_capabilities():
    return build_ui_capabilities()


@app.get("/api/perception/active-application")
async def active_application():
    try:
        return {"ok": True, **await asyncio.to_thread(read_active_application)}
    except RuntimeError as exc:
        return JSONResponse(
            {"ok": False, "code": "PERCEPTION_PROVIDER_UNAVAILABLE", "message": str(exc)},
            status_code=503,
        )


@app.middleware("http")
async def backend_api_auth_middleware(request: Request, call_next):
    if request.url.path in {"/api/ping", "/api/system/ui-capabilities"}:
        return await call_next(request)
    if request.url.path == HOST_DESKTOP_ACTION_PREFIX or request.url.path.startswith(
        f"{HOST_DESKTOP_ACTION_PREFIX}/"
    ):
        allowed, message = verify_host_desktop_action_authorization(
            request.headers.get("authorization"),
            os.getenv(HOST_DESKTOP_ACTION_TOKEN_ENV, ""),
            _BACKEND_API_TOKEN,
        )
        if not allowed:
            return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
        return await call_next(request)
    client_host = request.client.host if request.client else None
    if backend_api_auth_required(
        request.url.path,
        request.method,
        client_host=client_host,
    ):
        allowed, message = verify_backend_api_authorization(
            request.headers.get("authorization"),
            _BACKEND_API_TOKEN,
            request.headers.get("x-yuizaki-backend-token"),
            client_host=client_host,
        )
        if not allowed:
            return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
    return await call_next(request)

@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or f"trace_{uuid.uuid4().hex[:12]}"
    request.state.trace_id = trace_id
    logger.info("[trace:%s] %s %s", trace_id, request.method, request.url.path)
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(os.getenv("YUIZAKI_ALLOWED_ORIGINS")),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-trace-id", "x-yuizaki-backend-token"],
)

app.include_router(settings_router)

# ============ Memory / RAG 路由 ============
from modules.memory.routes import MemoryState, create_memory_pipeline_router, create_memory_router  # noqa: E402
from modules.agent.host_control import (  # noqa: E402
    create_computer_use_host_router,
    create_desktop_action_host_router,
)
from modules.system.relationship_policy import (  # noqa: E402
    is_relationship_milestone,
    normalize_relationship_importance,
    resolve_relationship_scope,
    summarize_relationship_events,
)
_apply_persisted_memory_config_before_backend_init()
_memory_state = MemoryState(store=create_memory_backend(config.memory))
_retrieval_pipeline = RetrievalPipeline(_memory_state.store)
_memory_state.pipeline = _retrieval_pipeline
sio_server.runtime.agent_pipeline.bind_retrieval_pipeline(_retrieval_pipeline)

runtime_health_providers = build_app_runtime_health_providers(
    llm_client_provider=lambda: _llm_client,
    tts_client_provider=lambda: _tts_client,
    asr_manager_provider=lambda: _asr_manager,
    ocr_client_provider=lambda: _ocr_client,
    database_repository_provider=lambda: db_repo,
    memory_state_provider=lambda: _memory_state,
)

onboarding_readiness = OnboardingReadiness(
    llm_client_provider=lambda: _llm_client,
    tts_client_provider=lambda: _tts_client,
    asr_manager_provider=lambda: _asr_manager,
    database_repository_provider=lambda: db_repo,
    memory_state_provider=lambda: _memory_state,
    mcp_manager_provider=lambda: sio_server.mcp_manager,
)


_write_relationship_memory = build_relationship_memory_writer(
    get_active_workspace_id=_get_active_workspace_id,
    get_db_repo=lambda: db_repo,
    get_memory_store=_get_memory_store,
    resolve_relationship_scope=resolve_relationship_scope,
    normalize_relationship_importance=normalize_relationship_importance,
)

_recent_relationship_history = build_recent_relationship_history_provider(
    get_active_workspace_id=_get_active_workspace_id,
    get_db_repo=lambda: db_repo,
    get_memory_store=_get_memory_store,
    limit=5,
)

_relationship_evolution_summary = build_relationship_summary_provider(
    get_recent_relationship_history=_recent_relationship_history,
    summarize_relationship_events=summarize_relationship_events,
)


def _companion_runtime_snapshot(limit: int = 8) -> dict[str, Any]:
    return build_companion_runtime_snapshot(
        active_workspace_id=_get_active_workspace_id(),
        db_repo=db_repo,
        heartbeat_scheduler=_heartbeat_scheduler,
        memory_state=_memory_state,
        summarize_relationship_events=summarize_relationship_events,
        is_relationship_milestone=is_relationship_milestone,
        limit=limit,
        scheduler=sio_server.scheduler,
        job_event_log=sio_server.job_events,
    )


_companion_runtime_status = build_companion_runtime_endpoint(snapshot_provider=_companion_runtime_snapshot)


_companion_relationship_history: Callable[[str, int], dict[str, Any]] = build_companion_relationship_history_endpoint(
    memory_store_provider=_get_memory_store,
    summarize_relationship_events=summarize_relationship_events,
    is_relationship_milestone=is_relationship_milestone,
)

memory_router = create_memory_router(
    _memory_state,
    get_active_workspace_id=_get_active_workspace_id,
    clear_memory_references=lambda memory_ids: db_repo.clear_memory_references(memory_ids) if db_repo else 0,
    count_memory_references=lambda memory_ids: db_repo.count_memory_references(memory_ids) if db_repo else 0,
)
app.include_router(memory_router)
app.include_router(
    create_storage_router(
        audio_cache_dir=config.tts.audio_cache_dir,
        runtime_temp_dir=DEFAULT_RUNTIME_TEMP_DIR,
        memory_store_provider=_get_memory_store,
    )
)
app.include_router(create_database_router(lambda: db_repo, get_active_workspace_id=_get_active_workspace_id))
app.include_router(
    create_workspace_router(
        lambda: db_repo,
        lambda: sio_server.runtime.mcp_manager if sio_server and sio_server.runtime else None,
        get_active_workspace_id=_get_active_workspace_id,
    )
)
app.include_router(cast(Callable[..., Any], create_companion_router)(lambda: db_repo, relationship_history_handler=_companion_relationship_history))
app.include_router(i18n_router)
app.include_router(
    create_summary_router(
        get_generation_mgr=lambda: _generation_mgr,
        get_llm_client=lambda: _llm_client,
        get_summary_list_limiter=lambda: _summary_list_limiter,
        get_summary_detail_limiter=lambda: _summary_detail_limiter,
        get_summary_rewrite_limiter=lambda: _summary_rewrite_limiter,
        get_governance_alert_state=lambda: _governance_alert_store.state,
        save_governance_alert_state=_governance_alert_store.save,
        get_db_repo=lambda: db_repo,
        get_active_workspace_id=_get_active_workspace_id,
    )
)
app.include_router(
    create_ai_router(
        get_config=lambda: config,
        get_generation_mgr=lambda: _generation_mgr,
        get_llm_client=lambda: _llm_client,
        get_svc_client=lambda: _svc_client,
        get_agent_runtime=lambda: sio_server.runtime,
        get_db_repo=lambda: db_repo,
        get_relationship_writer=lambda: _write_relationship_memory,
        get_relationship_history=lambda: _recent_relationship_history(),
        get_relationship_summary=lambda: _relationship_evolution_summary(),
        logger=logger,
        get_active_workspace_id=_get_active_workspace_id,
    )
)
app.include_router(
    create_realtime_router(
        get_config=lambda: config,
        get_db_repo=lambda: db_repo,
        get_active_workspace_id=_get_active_workspace_id,
        get_relationship_writer=lambda: _write_relationship_memory,
    )
)
_connector_router = create_message_connector_router(
    registry_provider=lambda: _message_connector_registry,
    turn_service_provider=lambda: sio_server.runtime.turn_service if sio_server and sio_server.runtime else None,
    active_workspace_id_provider=_get_active_workspace_id,
    delivery_store_provider=lambda: sio_server.runtime.turn_store if sio_server and sio_server.runtime else None,
    fast_ack_connectors={"telegram", "qq", "wechat"},
    recovery_interval_seconds=15.0,
    recovery_metrics_path=data_dir_from_env() / "connector_recovery.json",
)
_connector_recovery_controller = getattr(_connector_router, "connector_recovery_controller", None)
app.include_router(_connector_router)
config.tts.audio_cache_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(config.tts.audio_cache_dir)), name="audio")

runtime_handlers = build_runtime_handlers(
    service_manager=service_manager,
    health_checker=health_checker,
    config_snapshot_provider=lambda: public_config_snapshot(config),
    sio_server=sio_server,
    active_workspace_state=_active_workspace_state,
    active_workspace_id_provider=_get_active_workspace_id,
    db_repo_provider=lambda: db_repo,
    heartbeat_scheduler_provider=lambda: _heartbeat_scheduler,
    companion_runtime_status=_companion_runtime_status,
    retrieval_pipeline_provider=lambda: _retrieval_pipeline,
    relationship_summary_provider=_relationship_evolution_summary,
    companion_runtime_provider=_companion_runtime_snapshot,
    voice_diagnostics_provider=voice_diagnostics,
    build_memory_query_request=build_memory_query_request,
    llm_health_provider=runtime_health_providers.llm,
    tts_health_provider=runtime_health_providers.tts,
    database_health_provider=runtime_health_providers.database,
    asr_health_provider=runtime_health_providers.asr,
    ocr_health_provider=runtime_health_providers.ocr,
    memory_health_provider=runtime_health_providers.memory,
    llm_client_provider=lambda: _llm_client,
    tts_client_provider=lambda: _tts_client,
    asr_manager_provider=lambda: _asr_manager,
    vision_client_provider=lambda: _vision_llm_client,
    generation_manager_provider=lambda: _generation_mgr,
    svc_client_provider=lambda: _svc_client,
    memory_status_provider=lambda: _get_memory_store().get_status() if _memory_state else None,
    onboarding_readiness=onboarding_readiness,
    product_metrics_consent_store=_product_metrics_consent_store,
    message_connector_registry=_message_connector_registry,
    stream_runtime_provider=lambda: _stream_runtime,
)
app.include_router(create_memory_pipeline_router(runtime_handlers.memory_pipeline_query, get_active_workspace_id=_get_active_workspace_id))
app.include_router(create_computer_use_host_router(
    stop=sio_server.emergency_stop_computer_use,
    status=sio_server.computer_use_status,
))
app.include_router(create_desktop_action_host_router(
    status=sio_server.desktop_action_status,
    enable=sio_server.enable_desktop_actions,
    disable=sio_server.disable_desktop_actions,
    rearm=sio_server.rearm_desktop_actions,
    stop=sio_server.emergency_stop_desktop_actions,
    heartbeat=sio_server.heartbeat_desktop_actions,
    discover=sio_server.discover_desktop_actions,
    grant=sio_server.grant_desktop_app,
    host_token_provider=lambda: os.getenv(HOST_DESKTOP_ACTION_TOKEN_ENV, ""),
    backend_token_provider=lambda: _BACKEND_API_TOKEN,
))

app.include_router(
    cast(Callable[..., Any], getattr(system_runtime_composition, "build_system_router_from_handlers"))(
        create_system_router=cast(Callable[..., Any], create_system_router),
        handlers=runtime_handlers,
    )
)

# ============ Socket.IO ASGI 挂载 ============
# Socket.IO 服务在 /socket.io 路径上运行，作为当前唯一实时链路
app.mount('/socket.io', sio_server.asgi_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_parse_port(os.getenv("SERVER_PORT"), 8001),
    )

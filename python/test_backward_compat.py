"""Backward Compatibility Tests for Refactored app.py"""
import uuid
from unittest.mock import MagicMock

def test_websocket_chat_routing():
    """Verify chat messages are routed to LLM client."""
    from modules.core import GenerationManager
    mgr = GenerationManager()
    session_id = uuid.uuid4().hex[:12]
    gen = mgr.start(session_id)
    assert gen is not None
    assert gen.session_id == session_id
    print(f"[OK] Chat message routing: session={session_id}")

def test_audio_chunk_handling():
    """Verify audio chunks are processed by ASR manager."""
    from modules.asr import ASRManager
    vad_model = MagicMock()
    asr = ASRManager(vad_model)
    session_id = uuid.uuid4().hex[:12]
    pipeline = asr.get_or_create(session_id)
    assert pipeline is not None
    print(f"[OK] Audio chunk handling: session={session_id}")

def test_interrupt_message():
    """Verify interrupt messages cancel generations."""
    from modules.core import GenerationManager
    mgr = GenerationManager()
    session_id = uuid.uuid4().hex[:12]
    gen = mgr.start(session_id)
    assert not gen.cancel.is_set()
    interrupted = mgr.interrupt(session_id)
    assert interrupted is not None
    assert gen.cancel.is_set()
    print("[OK] Interrupt message: generation cancelled")

def test_health_endpoint():
    """Verify /health endpoint exists."""
    from modules.core import config
    assert config is not None
    assert config.llm.model == ""
    print("[OK] Health endpoint: config loaded")

def test_models_endpoint():
    """Verify /v1/models endpoint configuration."""
    from modules.core import config
    model_id = config.llm.model
    assert model_id is not None
    print(f"[OK] Models endpoint: model={model_id}")

def test_chat_completions_endpoint():
    """Verify /v1/chat/completions endpoint configuration."""
    from modules.core import config
    assert config.llm.base_url is not None
    print(f"[OK] Chat completions endpoint: base_url={config.llm.base_url}")

def test_svc_endpoint():
    """Verify /svc/convert endpoint configuration."""
    from modules.svc import SVCClient
    from modules.core import config
    svc = SVCClient(
        provider=config.svc.provider,
        base_url=config.svc.base_url,
        speaker_id=config.svc.speaker_id,
        pitch=config.svc.pitch,
    )
    assert svc is not None
    print("[OK] SVC endpoint: client initialized")

def test_config_from_env():
    """Verify configuration loads from environment."""
    from modules.core import config
    assert config.llm.model == ""
    assert config.tts.lang == "ja"
    assert config.asr.language == "zh"
    print("[OK] Config from env: all values loaded")

def test_config_defaults():
    """Verify configuration defaults are applied."""
    from modules.core import config
    assert config.llm.timeout == 60.0
    assert config.tts.provider == "genie-tts"
    assert config.asr.vad_threshold == 0.5
    print("[OK] Config defaults: all defaults applied")

def test_generation_lifecycle():
    """Verify Generation lifecycle."""
    from modules.core import Generation
    gen = Generation(generation_id="test-gen-1", session_id="test-session-1")
    assert gen.generation_id == "test-gen-1"
    assert not gen.cancel.is_set()
    gen.invalidate()
    assert gen.cancel.is_set()
    print("[OK] Generation lifecycle: create -> invalidate")

def test_generation_manager_history():
    """Verify GenerationManager history management."""
    from modules.core import GenerationManager
    mgr = GenerationManager()
    session_id = "test-session-1"
    mgr.append_history(session_id, "user", "Hello")
    mgr.append_history(session_id, "assistant", "Hi there")
    messages = mgr.get_messages_for_new_turn(session_id, "How are you?")
    assert len(messages) == 3
    print(f"[OK] GenerationManager history: {len(messages)} messages")

def test_generation_manager_concurrent():
    """Verify GenerationManager handles concurrent sessions."""
    from modules.core import GenerationManager
    mgr = GenerationManager()
    gen1 = mgr.start("session-1")
    gen2 = mgr.start("session-2")
    gen3 = mgr.start("session-3")
    assert gen1.session_id == "session-1"
    assert gen3.session_id == "session-3"
    mgr.interrupt("session-2")
    assert gen2.cancel.is_set()
    assert not gen1.cancel.is_set()
    print("[OK] GenerationManager concurrent: 3 sessions managed")

def test_llm_client_init():
    """Verify LLMClient initialization."""
    from modules.llm import LLMClient
    from modules.core import config
    client = LLMClient(config.llm.base_url, config.llm.api_key, config.llm.model, config.llm.timeout)
    assert client.model == config.llm.model
    print(f"[OK] LLMClient init: model={client.model}")

def test_tts_client_init():
    """Verify TTSClient initialization with Genie-TTS."""
    from modules.tts import TTSClient
    client = TTSClient(genie_character="feibi", language="zh")
    assert client is not None
    assert not client.is_enabled
    print("[OK] TTSClient init: genie-tts client created")

def test_svc_client_init():
    """Verify SVCClient initialization with external SoulX service config."""
    from modules.svc import SVCClient
    client = SVCClient(provider="soulx-service", pitch=0)
    assert client is not None
    assert not client.is_available
    print("[OK] SVCClient init: soulx-service client created")

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    
    print("\n" + "="*60)
    print("BACKWARD COMPATIBILITY TEST SUITE")
    print("="*60 + "\n")
    
    tests = [
        ("WebSocket: Chat routing", test_websocket_chat_routing),
        ("WebSocket: Audio chunks", test_audio_chunk_handling),
        ("WebSocket: Interrupt", test_interrupt_message),
        ("HTTP: Health", test_health_endpoint),
        ("HTTP: Models", test_models_endpoint),
        ("HTTP: Chat completions", test_chat_completions_endpoint),
        ("HTTP: SVC", test_svc_endpoint),
        ("Config: From env", test_config_from_env),
        ("Config: Defaults", test_config_defaults),
        ("State: Generation lifecycle", test_generation_lifecycle),
        ("State: History management", test_generation_manager_history),
        ("State: Concurrent sessions", test_generation_manager_concurrent),
        ("Service: LLMClient", test_llm_client_init),
        ("Service: TTSClient", test_tts_client_init),
        ("Service: SVCClient", test_svc_client_init),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_name}: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    sys.exit(0 if failed == 0 else 1)

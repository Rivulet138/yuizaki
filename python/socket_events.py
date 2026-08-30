"""
Socket.IO 事件命名空间与数据模型定义
统一前后端事件协议，Phase 2-5 逐步扩展
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════
#  事件名常量（前后端对齐）
# ═══════════════════════════════════════════════

class AudioEvents:
    """音频 & ASR 相关"""
    ASR_VAD_START = "asr:vad-start"
    ASR_SPEECH_START = "asr:speech-start"
    CHUNK       = "audio:chunk"       # ↑ 客户端 → 服务端: PCM16 音频块
    ASR_PARTIAL = "asr:partial"       # ↓ 服务端 → 客户端: 识别中间结果
    ASR_FINAL   = "asr:final"         # ↓ 服务端 → 客户端: 识别最终结果


class LLMEvents:
    """LLM 流式对话"""
    REQUEST = "llm:request"           # ↑ 客户端 → 服务端: 发送消息
    DELTA   = "llm:delta"             # ↓ 服务端 → 客户端: 流式 token
    FINAL   = "llm:final"             # ↓ 服务端 → 客户端: 完整响应


class TTSEvents:
    """TTS 语音合成"""
    CHUNK = "tts:chunk"               # ↓ 服务端 → 客户端: 音频流块
    DONE  = "tts:done"                # ↓ 服务端 → 客户端: 合成完成


class SVCEvents:
    """SVC 音色转换"""
    CONVERT = "svc:convert"           # ↑ 客户端 → 服务端
    DONE    = "svc:done"              # ↓ 服务端 → 客户端


class ToolEvents:
    """MCP 工具调用"""
    CALL   = "tool:call"              # ↑ 客户端 → 服务端 (LLM 决定)
    RESULT = "tool:result"            # ↓ 服务端 → 客户端: 成功结果
    ERROR  = "tool:error"             # ↓ 服务端 → 客户端: 调用失败
    RECHECK = "tool:recheck"           # ↑ 客户端 → 服务端: 无副作用状态探测
    RECHECK_RESULT = "tool:recheck-result"  # ↓ 服务端 → 客户端: 探测结果


class MemoryEvents:
    """记忆 / RAG"""
    STATUS = "memory:status"          # ↓ 索引状态推送
    QUERY  = "rag:query"              # ↑ RAG 查询
    RESULT = "rag:result"             # ↓ RAG 结果


class AgentEvents:
    """Agent 对话 / 计划事件"""
    CHAT   = "agent:chat"    # ↑ 前端 → Agent
    UPDATE = "agent:update"  # ↓ Agent 中间状态（预留）
    RESULT = "agent:result"  # ↓ Agent 最终结果（预留）


class ScreenshotEvents:
    CAPTURE_REQUEST = "screenshot:capture-request"
    REQUEST = "screenshot:request"
    RESULT = "screenshot:result"


class PetEvents:
    """桌宠状态同步"""
    STATE    = "pet:state"            # 双向: 位置/表情/模式同步
    INTERACT = "pet:interact"         # ↑ 交互事件 (点击、拖动)
    CONTROL  = "pet:control"          # ↓ LLM 触发的桌宠控制指令


class SystemEvents:
    """系统级别"""
    CONNECT    = "connect"
    DISCONNECT = "disconnect"
    ERROR      = "error"
    HEARTBEAT  = "heartbeat"          # 双向: 保活
    INTERRUPT  = "interrupt"          # ↑ 客户端 → 服务端: 中断当前 generation
    INTERRUPT_ACK = "interrupt:ack"
    LATENCY    = "system:latency"     # Backend stage timings for voice/chat diagnostics
    CLIENT_TIMING = "system:client-timing"
    PERMISSION_REQUEST = "permission:request"
    PERMISSION_RESPONSE = "permission:response"


# ═══════════════════════════════════════════════
#  事件数据模型 (dataclass → dict 序列化)
# ═══════════════════════════════════════════════

@dataclass
class AudioChunkData:
    """音频块数据"""
    chunk: str                        # base64 编码的 PCM16
    sample_rate: int = 16000
    is_final: bool = False


@dataclass
class ASRResultData:
    """ASR 识别结果"""
    text: str
    confidence: float = 0.0
    lang: str = "zh"


@dataclass
class LLMRequestData:
    """LLM 请求"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    max_tokens: int = 8192


@dataclass
class LLMDeltaData:
    """LLM 流式 token"""
    token: str
    index: int = 0
    session_id: str = ""
    generation_id: str = ""
    turn_id: str = ""
    request_id: str = ""
    interruption_epoch: int = 0
    version: int = 1
    sequence: int = 0


@dataclass
class LLMFinalData:
    """LLM 完整响应"""
    text: str
    session_id: str = ""
    total_tokens: int = 0
    finish_reason: str = "stop"
    user_message_id: Optional[int] = None
    assistant_message_id: Optional[int] = None
    generation_id: str = ""
    turn_id: str = ""
    request_id: str = ""
    interruption_epoch: int = 0
    version: int = 1
    sequence: int = 0
    tts_expected: Optional[bool] = None


@dataclass
class TTSVisemeCueData:
    viseme: str
    offset_ms: float
    duration_ms: Optional[float] = None
    weight: Optional[float] = None


@dataclass
class TTSChunkData:
    """TTS 音频块"""
    audio: bytes
    audio_format: str = "pcm_s16le"
    sample_rate: int = 32000
    channels: int = 1
    sample_width_bytes: int = 2
    duration_ms: Optional[float] = None
    session_id: str = ""
    generation_id: str = ""
    turn_id: str = ""
    request_id: str = ""
    interruption_epoch: int = 0
    version: int = 1
    sequence: int = 0
    chunk_index: int = 0
    is_final: bool = False
    text: str = ""
    visemes: List[TTSVisemeCueData] = field(default_factory=list)


TOOL_PROTOCOL_VERSION = 1
TOOL_EVENT_SCHEMA_VERSION = "yuizaki.tool-event.v1"

@dataclass


class ToolCallData:
    """工具调用请求"""
    id: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    source: Optional[str] = None
    retry: bool = False
    version: int = TOOL_PROTOCOL_VERSION


@dataclass
class ToolResultData:
    """工具调用结果"""
    id: str
    output: str = ""
    error: Optional[str] = None
    version: int = TOOL_PROTOCOL_VERSION
    status: str = "completed"
    outcome: str = "known_success"
    effect_outcome: Optional[str] = None
    verification_status: Optional[str] = None
    recheck_available: bool = False
    retryable: bool = False
    data: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    source: Optional[str] = None
    verification_evidence: Optional[List[str]] = None
    recheck_error: Optional[str] = None
    result_summary: Optional[str] = None


@dataclass
class ScreenshotRequestData:
    image: Optional[str] = None
    display_index: int = 0
    region: Optional[Dict[str, int]] = None
    mode: str = "observe"
    caption: Optional[str] = None
    source: Optional[str] = None
    timestamp: Optional[float] = None
    frame_id: Optional[str] = None


@dataclass
class PetStateData:
    """桌宠状态"""
    position_x: float = 0.0
    position_y: float = 0.0
    expression: str = ""
    animation: str = ""
    mode: str = "passive"             # passive | interact


@dataclass
class PetExpressionMixItemData:
    expression: str
    weight: float = 1.0


@dataclass
class PetParameterOverrideItemData:
    id: str
    value: float
    weight: float = 1.0


@dataclass
class PetMotionTargetData:
    group: str
    index: int = 0


@dataclass
class PetControlDirectiveData:
    expressionMix: List[PetExpressionMixItemData] = field(default_factory=list)
    parameterOverrides: List[PetParameterOverrideItemData] = field(default_factory=list)
    motion: Optional[PetMotionTargetData] = None
    intensity: float = 1.0
    durationMs: int = 1800


@dataclass
class HeartbeatData:
    """心跳"""
    timestamp: float = 0.0
    client_id: str = ""


def to_dict(data) -> dict:
    """序列化 dataclass 为 dict"""
    if hasattr(data, '__dataclass_fields__'):
        return asdict(data)
    return data

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    role: MessageRole
    content: str


class PetControlModelRef(BaseModel):
    id: str
    type: Literal["live2d", "vrm"]


class PetControlMotionOption(BaseModel):
    group: str
    index: int = 0


class PetControlParameterOption(BaseModel):
    id: str
    min: float = -1.0
    max: float = 1.0


class PetControlContext(BaseModel):
    models: list[PetControlModelRef] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    motionGroups: list[str] = Field(default_factory=list)
    motionOptions: list[PetControlMotionOption] = Field(default_factory=list)
    expressions: list[str] = Field(default_factory=list)
    parameters: list[PetControlParameterOption] = Field(default_factory=list)
    capabilityRevision: str | None = None
    modelType: Literal["live2d", "vrm"] | None = None
    modelId: str | None = None
    actions: dict[str, bool] = Field(default_factory=dict)
    viseme: bool | None = None
    avatarPrompt: str | None = None


# 入站消息（Renderer → Python）

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None
    request_id: str | None = None


class InterruptRequest(BaseModel):
    pass


class AudioChunkRequest(BaseModel):
    chunk: str  # base64 PCM16 16kHz
    is_final: bool = False


class SVCConvertRequest(BaseModel):
    audio: str  # base64 WAV
    speaker_id: int = 0
    transpose: int = 0


# 出站消息（Python → Renderer）

class TokenResponse(BaseModel):
    type: Literal["token"] = "token"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, content: str, session_id: str, **kwargs: object):
        super().__init__(
            data={"content": content, "session_id": session_id},
            **kwargs
        )


class DoneResponse(BaseModel):
    type: Literal["done"] = "done"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, session_id: str, total_tokens: int, **kwargs: object):
        super().__init__(
            data={"session_id": session_id, "total_tokens": total_tokens},
            **kwargs
        )


class TTSAudioResponse(BaseModel):
    type: Literal["tts_audio"] = "tts_audio"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, audio_url: str, duration_ms: int, **kwargs: object):
        super().__init__(
            data={"audio_url": audio_url, "duration_ms": duration_ms},
            **kwargs
        )


class ASRPartialResponse(BaseModel):
    type: Literal["asr_partial"] = "asr_partial"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, text: str, **kwargs: object):
        super().__init__(
            data={"text": text},
            **kwargs
        )


class ASRFinalResponse(BaseModel):
    type: Literal["asr_final"] = "asr_final"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, text: str, **kwargs: object):
        super().__init__(
            data={"text": text},
            **kwargs
        )


class SVCAudioResponse(BaseModel):
    type: Literal["svc_audio"] = "svc_audio"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, audio_url: str, **kwargs: object):
        super().__init__(
            data={"audio_url": audio_url},
            **kwargs
        )


class ErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    data: dict[str, object] = Field(default_factory=dict)

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None, **kwargs: object):
        super().__init__(
            data={"code": code, "message": message, "details": details or {}},
            **kwargs
        )


# HTTP 响应

class HealthResponse(BaseModel):
    status: Literal["ok", "error"]


class Model(BaseModel):
    id: str
    object: str


class ModelsResponse(BaseModel):
    object: Literal["list"]
    data: list[Model]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    session_id: str | None = None
    workspace_id: str | None = None
    request_id: str | None = None
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    mcp_enabled: bool | None = None
    web_search_enabled: bool | None = None
    pet_control_context: PetControlContext | None = None
    autonomy_mode: Literal["companion", "assistant", "executor", "reflector", "silent"] = "companion"


class SVCConvertResponse(BaseModel):
    generation_id: str
    status: Literal["processing", "done", "failed"]


class SVCStatusResponse(BaseModel):
    status: Literal["processing", "done", "failed"]
    audio_url: str | None = None
    error: str | None = None

from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from enum import Enum


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
    models: List[PetControlModelRef] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    motionGroups: List[str] = Field(default_factory=list)
    motionOptions: List[PetControlMotionOption] = Field(default_factory=list)
    expressions: List[str] = Field(default_factory=list)
    parameters: List[PetControlParameterOption] = Field(default_factory=list)
    avatarPrompt: Optional[str] = None


# 入站消息（Renderer → Python）

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    request_id: Optional[str] = None


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
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, content: str, session_id: str, **kwargs: object):
        super().__init__(
            data={"content": content, "session_id": session_id},
            **kwargs
        )


class DoneResponse(BaseModel):
    type: Literal["done"] = "done"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, session_id: str, total_tokens: int, **kwargs: object):
        super().__init__(
            data={"session_id": session_id, "total_tokens": total_tokens},
            **kwargs
        )


class TTSAudioResponse(BaseModel):
    type: Literal["tts_audio"] = "tts_audio"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, audio_url: str, duration_ms: int, **kwargs: object):
        super().__init__(
            data={"audio_url": audio_url, "duration_ms": duration_ms},
            **kwargs
        )


class ASRPartialResponse(BaseModel):
    type: Literal["asr_partial"] = "asr_partial"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, text: str, **kwargs: object):
        super().__init__(
            data={"text": text},
            **kwargs
        )


class ASRFinalResponse(BaseModel):
    type: Literal["asr_final"] = "asr_final"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, text: str, **kwargs: object):
        super().__init__(
            data={"text": text},
            **kwargs
        )


class SVCAudioResponse(BaseModel):
    type: Literal["svc_audio"] = "svc_audio"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, audio_url: str, **kwargs: object):
        super().__init__(
            data={"audio_url": audio_url},
            **kwargs
        )


class ErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    data: dict[str, object] = Field(default_factory=lambda: {})

    def __init__(self, code: str, message: str, details: Optional[dict[str, object]] = None, **kwargs: object):
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
    data: List[Model]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    request_id: Optional[str] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    mcp_enabled: Optional[bool] = None
    web_search_enabled: Optional[bool] = None
    pet_control_context: Optional[PetControlContext] = None


class SVCConvertResponse(BaseModel):
    generation_id: str
    status: Literal["processing", "done", "failed"]


class SVCStatusResponse(BaseModel):
    status: Literal["processing", "done", "failed"]
    audio_url: Optional[str] = None
    error: Optional[str] = None

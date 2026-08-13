export interface ChatArtifactRef {
  id?: string;
  name?: string;
  type?: string;
  url?: string;
}

export interface ChatAgentStep {
  id: string;
  title: string;
  status: string;
  tool?: string;
  error?: string;
  jobId?: string;
  runId?: string;
  resultSummary?: string;
  durationMs?: number;
  artifactCount?: number;
  artifacts?: ChatArtifactRef[];
  progress?: number;
}

export interface ChatMemorySource {
  id: string;
  text: string;
  layer?: string;
  source?: string;
  score?: number;
  confidence?: number;
  traceId?: string;
  eventId?: string;
  modelVersion?: string;
  correctionState?: 'none' | 'corrected' | 'forgotten';
}

export interface ChatMessage {
  id?: number | string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string | null;
  request_id?: string | null;
  tool_trace?: unknown[] | null;
  memory_trace?: unknown[] | null;
  agentSteps?: ChatAgentStep[] | null;
  memorySources?: ChatMemorySource[] | null;
}

export type ChatReasoningEffort =
  | 'default'
  | 'none'
  | 'minimal'
  | 'low'
  | 'medium'
  | 'high'
  | 'xhigh'
  | 'auto';

export type ChatPromptMode = 'auto' | 'work' | 'daily';
export type ChatResponseMode = 'instant' | 'balanced' | 'deep';
export type ChatVoiceMode = 'push-to-talk' | 'continuous';

export interface ChatPromptRoleCard {
  enabled?: boolean;
  name?: string;
  personality?: string;
  scenario?: string;
  instructions?: string;
  firstMessage?: string;
}

export interface ChatPromptEngineering {
  workPrompt?: string;
  dailyPrompt?: string;
}

export interface ChatPromptWorldBookEntry {
  id?: string;
  title?: string;
  keys?: string[];
  secondaryKeys?: string[];
  content?: string;
  enabled?: boolean;
  priority?: number;
  insertionOrder?: number;
  constant?: boolean;
  selective?: boolean;
  caseSensitive?: boolean;
  matchWholeWords?: boolean;
  probability?: number;
}

export interface ChatPromptWorldBook {
  enabled?: boolean;
  scanDepth?: number;
  maxEntries?: number;
  budgetTokens?: number;
  entries?: ChatPromptWorldBookEntry[];
}

export interface ChatPromptProfile {
  mode?: ChatPromptMode;
  promptEngineering?: ChatPromptEngineering;
  roleCard?: ChatPromptRoleCard;
  worldBook?: ChatPromptWorldBook;
}

export interface ChatOptions {
  model?: string;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  min_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  repetition_penalty?: number;
  max_tokens?: number;
  reasoning_effort?: ChatReasoningEffort;
  response_mode?: ChatResponseMode;
  voice_mode?: ChatVoiceMode;
  mcp_enabled?: boolean;
  web_search_enabled?: boolean;
  tts_enabled?: boolean;
  pet_link_enabled?: boolean;
  translation_target?: string;
  prompt_mode?: ChatPromptMode;
  prompt_profile?: ChatPromptProfile;
}

export interface ChatAttachment {
  id: string;
  name: string;
  type: string;
  size: number;
  kind: 'text' | 'image' | 'binary';
  content?: string;
}

export interface PetControlContextPayload {
  models: Array<{ id: string; type: 'live2d' | 'vrm' }>
  emotions: string[]
  motionGroups: string[]
  motionOptions: Array<{ group: string; index: number }>
  expressions: string[]
  parameters: Array<{ id: string; min: number; max: number }>
  /** Snapshot identity used to reject commands generated for an older model. */
  capabilityRevision?: string
  modelType?: 'live2d' | 'vrm'
  modelId?: string | null
  /** High-level support flags; omitted for legacy/catalog-only contexts. */
  actions?: Partial<{
    behavior: boolean
    affect: boolean
    gaze: boolean
    motion: boolean
    expression: boolean
    parameterPatch: boolean
    viseme: boolean
    cancel: boolean
  }>
  viseme?: boolean
  avatarPrompt?: string
}


// HTTP 响应类型

export interface OCRBlock {
  text: string;
  bbox: [number, number, number, number];
  confidence?: number;
}

export interface HealthResponse {
  status: 'ok' | 'error';
}

export interface Model {
  id: string;
  object: string;
}

export interface ModelsResponse {
  object: 'list';
  data: Model[];
}

export interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  min_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  repetition_penalty?: number;
  max_tokens?: number;
  reasoning_effort?: ChatReasoningEffort;
  mcp_enabled?: boolean;
  web_search_enabled?: boolean;
  tts_enabled?: boolean;
  prompt_mode?: ChatPromptMode;
  prompt_profile?: ChatPromptProfile;
}

export interface OCRResponse {
  status?: 'ok' | 'error';
  text: string;
  blocks: OCRBlock[];
  error?: string;
}

export interface SVCConvertResponse {
  generation_id: string;
  status: 'processing' | 'done' | 'failed';
}

export interface SVCStatusResponse {
  status: 'processing' | 'done' | 'failed';
  audio_url?: string;
  error?: string;
}

// 应用状态类型

export interface ChatState {
  messages: ChatMessage[];
  isGenerating: boolean;
  isSpeaking: boolean;
  currentSessionId: string;
}

export interface AudioState {
  isRecording: boolean;
  isPlaying: boolean;
  currentAudioUrl?: string;
}

export interface AppState {
  chat: ChatState;
  audio: AudioState;
  wsConnected: boolean;
  socketConnected: boolean;
  pythonRunning: boolean;
  petInteractMode: boolean;
}

// ═══════════════════════════════════════════════
//  Socket.IO 事件数据类型（与 backend/socket_events.py 对齐）
// ═══════════════════════════════════════════════

export interface SIOAudioChunkData {
  chunk: string;           // base64 PCM16
  sample_rate: number;
  is_final: boolean;
}

export interface SIOASRResultData {
  text: string;
  confidence: number;
  lang: string;
}

export interface SIOLLMRequestData {
  messages: ChatMessage[];
  session_id: string;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  min_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  repetition_penalty?: number;
  max_tokens?: number;
  chat_options?: ChatOptions;
}

export interface SIOLLMDeltaData {
  token: string;
  index: number;
  session_id: string;
}

export interface SIOLLMFinalData {
  text: string;
  session_id: string;
  total_tokens: number;
  finish_reason: string;
  user_message_id?: number | string | null;
  assistant_message_id?: number | string | null;
}

export interface SIOToolCallData {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface SIOToolResultData {
  id: string;
  output: string;
  error?: string;
}

export interface SIOScreenshotRequestData {
  image: string;
  display_index: number;
  region?: { x: number; y: number; width: number; height: number };
  mode?: 'observe' | 'frame' | 'vision' | 'ocr';
  caption?: string;
  source?: 'desktop' | 'window' | 'region' | 'pet';
  timestamp?: number;
  frame_id?: string;
  change_score?: number;
  capture_reason?: 'initial' | 'change' | 'voice_change' | 'heartbeat' | 'manual';
}

export interface ScreenCaptureEncodingOptions {
  maxWidth?: number
  maxHeight?: number
  format?: 'png' | 'jpeg'
  quality?: number
  privacyMasks?: Array<{ x: number; y: number; width: number; height: number }>
}

export interface SIOPetStateData {
  position_x: number;
  position_y: number;
  expression: string;
  animation: string;
  mode: 'passive' | 'interact';
}

// ═══════════════════════════════════════════════
//  Live2D 相关类型
// ═══════════════════════════════════════════════

export interface Live2DModelConfig {
  modelPath: string;
  scale: number;
  positionX: number;
  positionY: number;
}

export interface Live2DInteractEvent {
  type: 'tap' | 'drag' | 'hover';
  position?: { x: number; y: number };
}

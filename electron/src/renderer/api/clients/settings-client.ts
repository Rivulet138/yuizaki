import { CONTROL_ORIGIN, requestBlob, requestJson } from './http-client'

const MODEL_CONNECTION_TIMEOUT_MS = 60_000
const TTS_WARMUP_TIMEOUT_MS = 5 * 60 * 1000

export interface SettingsResponse {
  llm: LlmSettingsResponse
  tts: TtsSettingsResponse
  asr: {
    provider: 'sensevoice-service' | 'funasr-service' | 'openai-compatible' | 'sherpa-onnx' | 'sherpa-onnx-online' | 'sensevoice-local' | 'disabled'
    base_url: string
    api_key: string
    timeout?: number
    sensevoice_model: string
    sensevoice_device: string
    sherpa_model_path: string
    sherpa_tokens_path: string
    sherpa_num_threads: number
    sherpa_provider: 'cpu' | 'cuda' | 'coreml'
    language: string
    vad_threshold: number
    vad_min_silence_ms: number
    asr_partial_every: number
  }
  svc: {
    provider: 'soulx-service' | 'disabled'
    base_url: string
    speaker_id: number
    pitch: number
    timeout?: number
  }
  summary: {
    trigger_messages: number
    keep_recent_messages: number
    item_max_chars: number
    rewrite_interval_messages: number
    quality_scorer_mode: 'rule' | 'llm'
    quality_score_cooldown_seconds: number
    quality_score_budget_per_hour: number
  }
  system: {
    language: string
    theme: string
  }
  memory?: {
    backend?: string
    sqlite_path?: string
    qdrant_url?: string
    qdrant_api_key?: string
    qdrant_collection?: string
    qdrant_timeout?: number
    qdrant_auto_start?: boolean
    qdrant_docker_image?: string
    qdrant_docker_container?: string
    qdrant_docker_volume?: string
    embedding_model?: string
    reranker_enabled?: boolean
    reranker_model?: string
    reranker_candidate_count?: number
  }
}

export interface LlmProviderProfile {
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
  temperature?: number
  top_p?: number
  top_k?: number
  min_p?: number
  frequency_penalty?: number
  presence_penalty?: number
  repetition_penalty?: number
  timeout?: number
  context_max_tokens?: number
  default_max_output_tokens?: number
}

export interface LlmSettingsResponse {
    provider: string
    base_url: string
    api_key: string
    model: string
    temperature: number
    top_p: number
    top_k?: number
    min_p?: number
    frequency_penalty?: number
    presence_penalty?: number
    repetition_penalty?: number
    timeout?: number
    context_max_tokens?: number
    default_max_output_tokens?: number
    vision_enabled?: boolean
    vision_provider?: string
    vision_base_url?: string
    vision_api_key?: string
    vision_model?: string
    vision_timeout?: number
    vision_detail?: 'low' | 'high' | 'auto' | 'original'
    profiles?: Record<string, LlmProviderProfile>
}

export interface TtsSettingsResponse {
    genie_character: string
    genie_model_dir: string
    lang: string
    ref_audio: string
    ref_text: string
    device: 'cpu' | 'cuda'
    quality: string
    split: string
    mode: string
    save_mode: string
    provider: string
}

export interface SettingsMutationResponse {
  status: string
  updated?: number
  runtime_applied?: string[]
  runtime_changed?: string[]
}

export interface SettingsImportResponse {
  status: string
  filepath: string
  runtime_applied?: string[]
  runtime_changed?: string[]
}

export interface LlmModelsRequest {
  provider?: string
  base_url?: string
  api_key?: string
  timeout?: number
}

export interface LlmModelsResponse {
  ok: boolean
  models: string[]
  count?: number
  message?: string
}

export interface SettingsHistoryResponse {
  history: unknown[]
  count: number
}

export interface SettingsMetadataResponse {
  [key: string]: unknown
}

export interface SettingValueResponse {
  key: string
  value: unknown
}

export interface AdminTokenStatusResponse {
  hasToken: boolean
}

export interface AdminTokenMutationResponse {
  ok: boolean
  hasToken?: boolean
}

export interface BackendTokenStatusResponse {
  hasToken: boolean
  source: 'environment' | 'stored' | 'generated' | 'memory'
  storagePath?: string
  tokenPreview: string
  storedTokenPreview?: string
  requiresRestart: boolean
}

export interface BackendTokenMutationResponse {
  ok: boolean
  hasToken: boolean
  source: 'environment' | 'stored' | 'generated' | 'memory'
  tokenPreview: string
  requiresRestart: boolean
}

export interface TtsRuntimeStatusResponse {
  provider?: string
  available: boolean
  loading?: boolean
  warming_up?: boolean
  warmup_running?: boolean
  warmup_done?: boolean
  inference_running?: boolean
  character?: string
  language?: string
  configured_language?: string
  device?: string
  quality?: string
  split?: string
  mode?: string
  save_mode?: string
  split_sentence?: boolean
  streaming_transport?: 'pcm_s16le' | 'wav'
  streaming_sample_rate?: number | null
  capabilities?: TtsProviderCapabilities
  last_load_ms?: number | null
  last_load_queue_ms?: number | null
  last_load_model_ms?: number | null
  load_latency_summary?: {
    total?: TtsLatencySummary
    queue?: TtsLatencySummary
    model?: TtsLatencySummary
  }
  last_warmup_ms?: number | null
  last_warmup_queue_ms?: number | null
  last_warmup_inference_ms?: number | null
  warmup_latency_summary?: {
    total?: TtsLatencySummary
    queue?: TtsLatencySummary
    inference?: TtsLatencySummary
  }
  last_ready_wait_ms?: number | null
  ready_wait_latency_summary?: TtsLatencySummary
  last_generation_ms?: number | null
  generation_latency_summary?: TtsLatencySummary
  last_cancel_ms?: number | null
  cancel_latency_summary?: TtsLatencySummary
  cancel_count?: number
  last_error?: string | null
  message?: string
}

export interface TtsProviderCapabilities {
  provider: string
  locality: 'local' | 'cloud' | 'unknown'
  input_text_streaming: boolean
  output_audio_streaming: boolean
  output_transport: 'pcm_s16le' | 'wav' | 'unavailable'
  alignment: 'none' | 'character' | 'word' | 'viseme'
  viseme_vocabulary: string[]
  warmup: boolean
  cancellation: 'cooperative' | 'hard' | 'unavailable'
}

export interface TtsLatencySummary {
  samples: number
  latest_ms?: number | null
  p50_ms?: number | null
  p95_ms?: number | null
}

export interface TestConnectionResponse {
  ok?: boolean
  status?: string
  message?: string
  runtime?: TtsRuntimeStatusResponse
}

export interface TtsWarmupResponse {
  ok: boolean
  queued: boolean
  message?: string
  runtime?: TtsRuntimeStatusResponse
}

export interface LocalRuntimeCandidate {
  id: string
  label?: string
  provider?: string
  backend?: string
  base_url?: string
  qdrant_url?: string
  model_dir?: string
  model_dir_exists?: boolean
  ok: boolean
  installed?: boolean
  status_code?: number | null
  models?: string[]
  message?: string
}

export interface LocalRuntimeDiscoveryResponse {
  llm: LocalRuntimeCandidate[]
  asr: LocalRuntimeCandidate[]
  tts: LocalRuntimeCandidate[]
  svc: LocalRuntimeCandidate[]
  memory: LocalRuntimeCandidate[]
}

let loadSettingsRequest: Promise<SettingsResponse> | null = null

const loadSettings = async (): Promise<SettingsResponse> => {
  if (!loadSettingsRequest) {
    loadSettingsRequest = requestJson<SettingsResponse>(`${CONTROL_ORIGIN}/api/settings/`)
      .finally(() => {
        loadSettingsRequest = null
      })
  }
  return loadSettingsRequest
}

export const settingsClient = {
  load: loadSettings,
  exportBlob: async () => requestBlob(`${CONTROL_ORIGIN}/api/settings/export`),
  importPayload: async (payload: Record<string, unknown>) =>
    requestJson<SettingsImportResponse>(`${CONTROL_ORIGIN}/api/settings/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  save: async (payload: Record<string, unknown>) =>
    requestJson<SettingsMutationResponse>(`${CONTROL_ORIGIN}/api/settings/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  testLlm: async () => requestJson<TestConnectionResponse>(`${CONTROL_ORIGIN}/api/settings/test/llm`, { method: 'POST', timeoutMs: MODEL_CONNECTION_TIMEOUT_MS }),
  listLlmModels: async (payload: LlmModelsRequest) => requestJson<LlmModelsResponse>(`${CONTROL_ORIGIN}/api/settings/llm/models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  testTts: async () => requestJson<TestConnectionResponse>(`${CONTROL_ORIGIN}/api/settings/test/tts`, { method: 'POST', timeoutMs: MODEL_CONNECTION_TIMEOUT_MS }),
  ttsStatus: async () => requestJson<TtsRuntimeStatusResponse>(`${CONTROL_ORIGIN}/api/settings/tts/status`),
  warmupTts: async () => requestJson<TtsWarmupResponse>(`${CONTROL_ORIGIN}/api/settings/tts/warmup`, { method: 'POST', timeoutMs: TTS_WARMUP_TIMEOUT_MS }),
  discoverLocal: async () => requestJson<LocalRuntimeDiscoveryResponse>(`${CONTROL_ORIGIN}/api/settings/local-discovery`),
  metadata: async () => requestJson<SettingsMetadataResponse>(`${CONTROL_ORIGIN}/api/settings/metadata`),
  history: async () => requestJson<SettingsHistoryResponse>(`${CONTROL_ORIGIN}/api/settings/history`),
  clearHistory: async () => requestJson<SettingsMutationResponse>(`${CONTROL_ORIGIN}/api/settings/history`, { method: 'DELETE' }),
  rollback: async (steps: number) => requestJson<{ status: string; steps: number }>(`${CONTROL_ORIGIN}/api/settings/rollback?steps=${encodeURIComponent(String(steps))}`, { method: 'POST' }),
  getSetting: async (key: string) => requestJson<SettingValueResponse>(`${CONTROL_ORIGIN}/api/settings/${encodeURIComponent(key)}`),
  setSetting: async (key: string, value: unknown) => requestJson<SettingsMutationResponse>(`${CONTROL_ORIGIN}/api/settings/${encodeURIComponent(key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  }),
  deleteSetting: async (key: string) => requestJson<SettingsMutationResponse>(`${CONTROL_ORIGIN}/api/settings/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  adminTokenStatus: async () => requestJson<AdminTokenStatusResponse>(`${CONTROL_ORIGIN}/api/system/admin-token`),
  setAdminToken: async (token: string) => requestJson<AdminTokenMutationResponse>(`${CONTROL_ORIGIN}/api/system/admin-token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  }),
  clearAdminToken: async () => requestJson<{ ok: boolean }>(`${CONTROL_ORIGIN}/api/system/admin-token`, { method: 'DELETE' }),
  backendTokenStatus: async () => requestJson<BackendTokenStatusResponse>(`${CONTROL_ORIGIN}/api/system/backend-token`),
  setBackendToken: async (token: string) => requestJson<BackendTokenMutationResponse>(`${CONTROL_ORIGIN}/api/system/backend-token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  }),
  resetBackendToken: async () => requestJson<BackendTokenMutationResponse>(`${CONTROL_ORIGIN}/api/system/backend-token`, { method: 'DELETE' }),
}

import { ElMessage } from 'element-plus'
import { defineStore } from 'pinia'
import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { petControl } from '@/utils/petControl'
import { chatClient } from '@/api/client'
import { API_ORIGIN, CONTROL_ORIGIN, requestJson } from '@/api/clients/http-client'
import type { ActionEnvelope, ActionEnvelopeWithTrace } from '../../shared/agent'
import { isPetLipSyncViseme, type PetSentenceEmotionCue, type PetVisemeCue } from '../../shared/pet-control'
import type {
  ChatAgentStep,
  ChatMemorySource,
  ChatMessage,
  ChatOptions,
  ChatPromptMode,
  ChatPromptProfile,
  PetControlContextPayload,
} from '../../shared/types'
import { SocketEvents } from '../net/socketClient'
import { normalizeSentenceEmotionCues } from '../pet-sentence-emotion-scheduler'
import { useWorkspaceStore } from './workspaceStore'
import { logger } from '@/logger'
import {
  getCompanionInterruptionEpoch,
  publishCompanionInterrupt,
  publishCompanionRuntimeEvent,
} from '@/app/runtime/companionRuntime'

export interface ChatStoreState {
  messages: ChatMessage[]
  contextStartIndex: number
  adviceFeed: ChatAdviceItem[]
  isGenerating: boolean
  isSpeaking: boolean
  isTTSPlaying: boolean
  currentSessionId: string
  currentWorkspaceId: string
  currentText: string
  asrPartialText: string
  isRecording: boolean
  lastError: string | null
  lastAgentEnvelope: ActionEnvelope | null
  agentEnvelopeTimeline: ActionEnvelopeWithTrace[]
  voiceLatency: {
    asr: VoiceLatencySnapshot | null
    generation: VoiceLatencySnapshot | null
  }
}

export interface VoiceLatencySnapshot {
  kind: string
  stages: Record<string, number>
  totalMs: number
  updatedAt: string
}

export interface ChatAdviceItem {
  id: string
  content: string
  createdAt: string
  source: string
}

export interface ChatSessionRuntime {
  sessionId: string
  workspaceId: string
  requestId: string | null
  currentText: string
  isGenerating: boolean
  unread: boolean
}

type UnknownRecord = Record<string, unknown>
type SendChatOptions = {
  appendUser?: boolean
  chatOptions?: Partial<ChatOptions>
}
type RuntimeRequest = {
  requestId: string
  interruptionEpoch: number
  sessionId: string
  workspaceId: string
}
type AgentTurnPreparation = () => Promise<void>
type ChatHistoryRecord = {
  id?: number | string | null
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string | null
  request_id?: string | null
  tool_trace?: unknown[] | null
  memory_trace?: unknown[] | null
  agentSteps?: ChatAgentStep[] | null
  memorySources?: ChatMemorySource[] | null
}
type RealtimeTurnRecord = {
  turnId: string
  userText: string
  assistantText: string
  model: string
  workspaceId: string
  sessionId: string
}
type RealtimeTranscriptResponse = {
  status: string
  user_message?: ChatHistoryRecord
  assistant_message?: ChatHistoryRecord
}

const withWorkspaceQuery = (url: string, workspaceId?: string | null) => {
  const cleanWorkspaceId = workspaceId?.trim()
  return cleanWorkspaceId ? `${url}${url.includes('?') ? '&' : '?'}workspace_id=${encodeURIComponent(cleanWorkspaceId)}` : url
}

const createRequestId = () => `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
const createAdviceId = () => `advice_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
const CHAT_OPTIONS_STORAGE_KEY = 'yuizaki.chat.options'
const CHAT_OPTIONS_STORAGE_VERSION_KEY = 'yuizaki.chat.options.version'
const CHAT_OPTIONS_STORAGE_VERSION = '7'
const CHAT_OPTIONS_MAX_OUTPUT_TOKENS = 65535
const createTtsStopEvent = (detail?: { interrupted?: boolean; petLipSyncHandled?: boolean }) =>
  new CustomEvent('pet:tts-stop', { detail })

const DEFAULT_CHAT_OPTIONS: Required<Pick<ChatOptions, 'temperature' | 'top_p' | 'top_k' | 'min_p' | 'frequency_penalty' | 'presence_penalty' | 'repetition_penalty' | 'max_tokens' | 'reasoning_effort' | 'response_mode' | 'mcp_enabled' | 'web_search_enabled' | 'tts_enabled' | 'pet_link_enabled' | 'translation_target' | 'prompt_mode'>> & Pick<ChatOptions, 'model'> = {
  model: '',
  temperature: 1.2,
  top_p: 0.9,
  top_k: 500,
  min_p: 0,
  frequency_penalty: 0.2,
  presence_penalty: 0,
  repetition_penalty: 1,
  max_tokens: 8192,
  reasoning_effort: 'default',
  response_mode: 'balanced',
  mcp_enabled: true,
  web_search_enabled: false,
  tts_enabled: true,
  pet_link_enabled: true,
  translation_target: 'zh-CN',
  prompt_mode: 'auto',
}

const isRecord = (value: unknown): value is UnknownRecord => typeof value === 'object' && value !== null && !Array.isArray(value)

const readString = (value: unknown, key: string): string => {
  if (!isRecord(value)) return ''
  const field = value[key]
  return typeof field === 'string' ? field : ''
}

const readNumber = (value: unknown, key: string): number | undefined => {
  if (!isRecord(value)) return undefined
  const field = value[key]
  if (typeof field === 'number' && Number.isFinite(field)) return field
  if (typeof field === 'string' && field.trim()) {
    const parsed = Number(field)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

type PcmAudioPayload = {
  audio: Uint8Array
  audioFormat: 'pcm_s16le'
  sampleRate: number
  channels: number
  sampleWidthBytes: 2
}

const normalizeVisemeCues = (value: unknown): PetVisemeCue[] => {
  if (!Array.isArray(value)) return []
  return value
    .slice(0, 256)
    .flatMap((item): PetVisemeCue[] => {
      const viseme = readString(item, 'viseme')
      const offsetMs = readNumber(item, 'offset_ms')
      if (!isPetLipSyncViseme(viseme) || offsetMs === undefined || offsetMs < 0) return []
      const durationMs = readNumber(item, 'duration_ms')
      const weight = readNumber(item, 'weight')
      return [{
        viseme,
        offsetMs: Math.min(10 * 60 * 1_000, offsetMs),
        ...(durationMs !== undefined && durationMs > 0
          ? { durationMs: Math.min(60_000, durationMs) }
          : {}),
        ...(weight !== undefined ? { weight: Math.max(0, Math.min(1, weight)) } : {}),
      }]
    })
    .sort((left, right) => left.offsetMs - right.offsetMs)
}

const readBinaryBytes = (value: unknown): Uint8Array | null => {
  if (value instanceof Uint8Array) return value
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  }
  if (isRecord(value) && value.type === 'Buffer' && Array.isArray(value.data)) {
    const bytes = value.data.filter((item): item is number => (
      typeof item === 'number' && Number.isInteger(item) && item >= 0 && item <= 255
    ))
    return bytes.length === value.data.length ? Uint8Array.from(bytes) : null
  }
  return null
}

const readPcmAudio = (value: unknown): PcmAudioPayload | null => {
  if (!isRecord(value) || readString(value, 'audio_format') !== 'pcm_s16le') return null
  const audio = readBinaryBytes(value.audio)
  const sampleRate = readNumber(value, 'sample_rate')
  const channels = readNumber(value, 'channels')
  const sampleWidthBytes = readNumber(value, 'sample_width_bytes')
  if (
    !audio?.byteLength
    || !sampleRate
    || sampleRate < 8_000
    || sampleRate > 192_000
    || !channels
    || channels < 1
    || channels > 2
    || sampleWidthBytes !== 2
  ) return null
  return {
    audio,
    audioFormat: 'pcm_s16le',
    sampleRate,
    channels,
    sampleWidthBytes: 2,
  }
}

const normalizeLatencySnapshot = (value: unknown): VoiceLatencySnapshot | null => {
  if (!isRecord(value)) return null
  const kind = readString(value, 'kind')
  if (!kind || !isRecord(value.stages)) return null
  const stages: Record<string, number> = {}
  for (const [key, stageValue] of Object.entries(value.stages)) {
    const parsed = typeof stageValue === 'number' ? stageValue : Number(stageValue)
    if (Number.isFinite(parsed)) stages[key] = parsed
  }
  return {
    kind,
    stages,
    totalMs: readNumber(value, 'total_ms') ?? Math.max(0, ...Object.values(stages)),
    updatedAt: new Date().toISOString(),
  }
}

const clampNumber = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value))

const readMessageId = (value: unknown, key: string): number | string | undefined => {
  if (!isRecord(value)) return undefined
  const field = value[key]
  if (typeof field === 'number' && Number.isFinite(field)) return field
  if (typeof field === 'string' && field.trim()) return field
  return undefined
}

const normalizePromptMode = (value: unknown): ChatPromptMode =>
  value === 'work' || value === 'daily' || value === 'auto' ? value : DEFAULT_CHAT_OPTIONS.prompt_mode

const normalizePromptProfile = (value: unknown): ChatPromptProfile | undefined => {
  if (!isRecord(value)) return undefined
  const promptEngineering = isRecord(value.promptEngineering)
    ? {
        workPrompt: typeof value.promptEngineering.workPrompt === 'string' ? value.promptEngineering.workPrompt : undefined,
        dailyPrompt: typeof value.promptEngineering.dailyPrompt === 'string' ? value.promptEngineering.dailyPrompt : undefined,
      }
    : undefined
  const roleCard = isRecord(value.roleCard)
    ? {
        enabled: typeof value.roleCard.enabled === 'boolean' ? value.roleCard.enabled : undefined,
        name: typeof value.roleCard.name === 'string' ? value.roleCard.name : undefined,
        personality: typeof value.roleCard.personality === 'string' ? value.roleCard.personality : undefined,
        scenario: typeof value.roleCard.scenario === 'string' ? value.roleCard.scenario : undefined,
        instructions: typeof value.roleCard.instructions === 'string' ? value.roleCard.instructions : undefined,
        firstMessage: typeof value.roleCard.firstMessage === 'string' ? value.roleCard.firstMessage : undefined,
      }
    : undefined
  const worldBook = isRecord(value.worldBook)
    ? {
        enabled: typeof value.worldBook.enabled === 'boolean' ? value.worldBook.enabled : undefined,
        scanDepth: readNumber(value.worldBook, 'scanDepth'),
        maxEntries: readNumber(value.worldBook, 'maxEntries'),
        budgetTokens: readNumber(value.worldBook, 'budgetTokens'),
        entries: Array.isArray(value.worldBook.entries)
          ? value.worldBook.entries
              .filter(isRecord)
              .map((entry) => ({
                id: typeof entry.id === 'string' ? entry.id : undefined,
                title: typeof entry.title === 'string' ? entry.title : undefined,
                keys: Array.isArray(entry.keys) ? entry.keys.map(String).filter(Boolean) : undefined,
                secondaryKeys: Array.isArray(entry.secondaryKeys) ? entry.secondaryKeys.map(String).filter(Boolean) : undefined,
                content: typeof entry.content === 'string' ? entry.content : undefined,
                enabled: typeof entry.enabled === 'boolean' ? entry.enabled : undefined,
                priority: readNumber(entry, 'priority'),
                insertionOrder: readNumber(entry, 'insertionOrder'),
                constant: typeof entry.constant === 'boolean' ? entry.constant : undefined,
                selective: typeof entry.selective === 'boolean' ? entry.selective : undefined,
                caseSensitive: typeof entry.caseSensitive === 'boolean' ? entry.caseSensitive : undefined,
                matchWholeWords: typeof entry.matchWholeWords === 'boolean' ? entry.matchWholeWords : undefined,
                probability: readNumber(entry, 'probability'),
              }))
          : undefined,
      }
    : undefined

  const profile: ChatPromptProfile = {
    mode: normalizePromptMode(value.mode),
  }
  if (promptEngineering) profile.promptEngineering = promptEngineering
  if (roleCard) profile.roleCard = roleCard
  if (worldBook) profile.worldBook = worldBook
  return profile
}

const normalizeChatOptions = (value: unknown): ChatOptions => {
  const source = isRecord(value) ? value : {}
  const model = typeof source.model === 'string' ? source.model.trim() : ''
  const reasoningEffort = typeof source.reasoning_effort === 'string' ? source.reasoning_effort : DEFAULT_CHAT_OPTIONS.reasoning_effort
  const translationTarget = typeof source.translation_target === 'string' ? source.translation_target : DEFAULT_CHAT_OPTIONS.translation_target
  const promptProfile = normalizePromptProfile(source.prompt_profile)
  return {
    model,
    temperature: clampNumber(readNumber(source, 'temperature') ?? DEFAULT_CHAT_OPTIONS.temperature, 0, 2),
    top_p: clampNumber(readNumber(source, 'top_p') ?? DEFAULT_CHAT_OPTIONS.top_p, 0, 1),
    top_k: Math.max(0, Math.round(readNumber(source, 'top_k') ?? DEFAULT_CHAT_OPTIONS.top_k)),
    min_p: clampNumber(readNumber(source, 'min_p') ?? DEFAULT_CHAT_OPTIONS.min_p, 0, 1),
    frequency_penalty: clampNumber(readNumber(source, 'frequency_penalty') ?? DEFAULT_CHAT_OPTIONS.frequency_penalty, -2, 2),
    presence_penalty: clampNumber(readNumber(source, 'presence_penalty') ?? DEFAULT_CHAT_OPTIONS.presence_penalty, -2, 2),
    repetition_penalty: clampNumber(readNumber(source, 'repetition_penalty') ?? DEFAULT_CHAT_OPTIONS.repetition_penalty, 0, 2),
    max_tokens: Math.max(128, Math.min(CHAT_OPTIONS_MAX_OUTPUT_TOKENS, Math.round(readNumber(source, 'max_tokens') ?? DEFAULT_CHAT_OPTIONS.max_tokens))),
    reasoning_effort: ['default', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'auto'].includes(reasoningEffort)
      ? reasoningEffort as ChatOptions['reasoning_effort']
      : DEFAULT_CHAT_OPTIONS.reasoning_effort,
    response_mode: ['instant', 'balanced', 'deep'].includes(String(source.response_mode || ''))
      ? source.response_mode as ChatOptions['response_mode']
      : DEFAULT_CHAT_OPTIONS.response_mode,
    mcp_enabled: typeof source.mcp_enabled === 'boolean' ? source.mcp_enabled : DEFAULT_CHAT_OPTIONS.mcp_enabled,
    web_search_enabled: typeof source.web_search_enabled === 'boolean' ? source.web_search_enabled : DEFAULT_CHAT_OPTIONS.web_search_enabled,
    tts_enabled: typeof source.tts_enabled === 'boolean' ? source.tts_enabled : DEFAULT_CHAT_OPTIONS.tts_enabled,
    pet_link_enabled: typeof source.pet_link_enabled === 'boolean' ? source.pet_link_enabled : DEFAULT_CHAT_OPTIONS.pet_link_enabled,
    translation_target: translationTarget || DEFAULT_CHAT_OPTIONS.translation_target,
    prompt_mode: normalizePromptMode(source.prompt_mode),
    ...(promptProfile ? { prompt_profile: promptProfile } : {}),
  }
}

const loadChatOptions = (): ChatOptions => {
  if (typeof window === 'undefined') return { ...DEFAULT_CHAT_OPTIONS }
  try {
    const raw = window.localStorage.getItem(CHAT_OPTIONS_STORAGE_KEY)
    const normalized = normalizeChatOptions(raw ? JSON.parse(raw) : null)
    const version = window.localStorage.getItem(CHAT_OPTIONS_STORAGE_VERSION_KEY)
    if (version !== CHAT_OPTIONS_STORAGE_VERSION) {
      const migrated = normalizeChatOptions({
        ...normalized,
        temperature: normalized.temperature === 0.7 ? DEFAULT_CHAT_OPTIONS.temperature : normalized.temperature,
        top_p: normalized.top_p === 1 ? DEFAULT_CHAT_OPTIONS.top_p : normalized.top_p,
        max_tokens: normalized.max_tokens === 2048 ? DEFAULT_CHAT_OPTIONS.max_tokens : normalized.max_tokens,
        mcp_enabled: true,
        ...(version === '4' || version === '5' || version === '6' ? {} : { web_search_enabled: false }),
      })
      persistChatOptions(migrated)
      return migrated
    }
    return normalized
  } catch {
    return { ...DEFAULT_CHAT_OPTIONS }
  }
}

const persistChatOptions = (options: ChatOptions) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(CHAT_OPTIONS_STORAGE_KEY, JSON.stringify(normalizeChatOptions(options)))
  window.localStorage.setItem(CHAT_OPTIONS_STORAGE_VERSION_KEY, CHAT_OPTIONS_STORAGE_VERSION)
}

const normalizeActionEnvelope = (value: unknown): ActionEnvelope | null => {
  if (!isRecord(value)) return null
  const version = typeof value.version === 'number' ? value.version : 1
  const schema_version = typeof value.schema_version === 'string' ? value.schema_version : undefined
  const request_id = typeof value.request_id === 'string' ? value.request_id : ''
  const source = typeof value.source === 'string' ? value.source : ''
  const reply = typeof value.reply === 'string' ? value.reply : ''
  const actions = Array.isArray(value.actions)
    ? value.actions
        .filter(isRecord)
        .map((action) => ({
          type: typeof action.type === 'string' ? action.type : 'reply',
          content: typeof action.content === 'string' ? action.content : undefined,
          payload: action.payload,
          schema_version: typeof action.schema_version === 'string' ? action.schema_version : undefined,
          source: typeof action.source === 'string' ? action.source : undefined,
        }))
    : []

  return { version, schema_version, request_id, source, reply, actions }
}

export const useChatStore = defineStore('chat', () => {
  const workspaceStore = useWorkspaceStore()
  const state = reactive<ChatStoreState>({
    messages: [],
    contextStartIndex: 0,
    adviceFeed: [],
    isGenerating: false,
    isSpeaking: false,
    isTTSPlaying: false,
    currentSessionId: 'default',
    currentWorkspaceId: 'default',
    currentText: '',
    asrPartialText: '',
    isRecording: false,
    lastError: null,
    lastAgentEnvelope: null,
    agentEnvelopeTimeline: [],
    voiceLatency: {
      asr: null,
      generation: null,
    },
  })
  type TraceMetadata = {
    tool_trace?: unknown[]
    memory_trace?: unknown[]
    agentSteps?: ChatAgentStep[]
    memorySources?: ChatMemorySource[]
  }
  const pendingMessageTraces = new Map<string, TraceMetadata>()

  const normalizeAgentSteps = (items: unknown[]): ChatAgentStep[] => items.flatMap((item, index) => {
    if (!isRecord(item)) return []
    const id = String(item.id ?? item.step_id ?? `step-${index + 1}`).trim()
    const tool = String(item.tool ?? '').trim()
    const title = String(item.title || item.description || tool || `步骤 ${index + 1}`).trim()
    if (!title) return []
    const success = typeof item.success === 'boolean' ? item.success : undefined
    const status = String(item.status ?? (success === false ? 'failed' : success === true ? 'completed' : 'recorded')).trim()
    const error = String(item.error ?? '').trim()
    return [{ id, title, status, ...(tool ? { tool } : {}), ...(error ? { error } : {}) }]
  })

  const normalizeMemorySources = (items: unknown[]): ChatMemorySource[] => items.flatMap((item) => {
    if (!isRecord(item)) return []
    const doc = isRecord(item.doc) ? item.doc : item
    const metadata = isRecord(doc.metadata) ? doc.metadata : {}
    const id = String(doc.id ?? item.document_id ?? '').trim()
    const text = String(doc.text ?? doc.content ?? '').trim()
    if (!id || !text) return []
    const layer = String(doc.layer ?? metadata.layer ?? '').trim()
    const source = String(doc.source ?? metadata.source ?? '').trim()
    const score = typeof item.score === 'number' && Number.isFinite(item.score) ? item.score : undefined
    return [{ id, text, ...(layer ? { layer } : {}), ...(source ? { source } : {}), ...(score !== undefined ? { score } : {}) }]
  })

  const readTraceMetadata = (data: unknown) => {
    if (!isRecord(data)) return null
    const actions = Array.isArray(data.actions) ? data.actions.filter(isRecord) : []
    const tool = Array.isArray(data.tool_trace) ? data.tool_trace : actions.flatMap((a) => a.type === 'tool_trace' && Array.isArray(a.payload) ? a.payload : [])
    const memory = Array.isArray(data.memory_trace) ? data.memory_trace : actions.flatMap((a) => a.type === 'memory_trace' && Array.isArray(a.payload) ? a.payload : [])
    if (!tool.length && !memory.length) return null
    const visibleToolSteps = tool.flatMap((item) => {
      if (!isRecord(item)) return []
      return Array.isArray(item.step_results) ? item.step_results : [item]
    })
    const agentSteps = normalizeAgentSteps(visibleToolSteps)
    const memorySources = normalizeMemorySources(memory)
    return {
      ...(tool.length ? { tool_trace: tool } : {}),
      ...(agentSteps.length ? { agentSteps } : {}),
      ...(memory.length ? { memory_trace: memory } : {}),
      ...(memorySources.length ? { memorySources } : {}),
    }
  }

  const petControlContext = ref<PetControlContextPayload | null>(null)
  const companionPersonaPrompt = ref<string | null>(null)
  const promptProfile = ref<ChatPromptProfile | null>(null)
  const chatOptions = reactive<ChatOptions>(loadChatOptions())
  const sessionRuntime = reactive<Record<string, ChatSessionRuntime>>({})
  watch(chatOptions, () => persistChatOptions(chatOptions), { deep: true })
  let pendingSentenceEmotionCues: PetSentenceEmotionCue[] = []
  let lastAssistantText = ''
  let initialized = false
  const pendingUserMessages = new Map<string, { content: string; index: number }>()
  const pendingInterrupts = new Map<string, { startedAt: number; sessionId: string; timeoutId: number }>()
  const runtimeRequests = new Map<string, RuntimeRequest>()
  let currentRuntimeRequest: RuntimeRequest | null = null
  let currentRealtimeRuntimeRequest: { requestId: string; interruptionEpoch: number } | null = null
  let agentTurnPreparation: AgentTurnPreparation | null = null
  let historyLoadEpoch = 0
  const blockedTtsGenerations = new Set<string>()
  const reportedPlaybackGenerations = new Set<string>()

  const ensureSessionRuntime = (sessionId: string, workspaceId = state.currentWorkspaceId): ChatSessionRuntime => {
    const id = sessionId.trim() || 'default'
    const existing = sessionRuntime[id]
    if (existing) {
      if (workspaceId) existing.workspaceId = workspaceId
      return existing
    }
    const created: ChatSessionRuntime = {
      sessionId: id,
      workspaceId: workspaceId.trim() || 'default',
      requestId: null,
      currentText: '',
      isGenerating: false,
      unread: false,
    }
    sessionRuntime[id] = created
    return created
  }

  const resolveEventRuntime = (data: unknown): ChatSessionRuntime | null => {
    const sessionId = readString(data, 'session_id').trim()
    if (sessionId) return ensureSessionRuntime(sessionId)
    const requestId = readString(data, 'request_id').trim()
    const request = requestId ? runtimeRequests.get(requestId) : undefined
    if (request) return ensureSessionRuntime(request.sessionId, request.workspaceId)
    const running = Object.values(sessionRuntime).filter((runtime) => runtime.isGenerating)
    if (running.length > 1) return null
    if (running.length === 1 && running[0].sessionId !== state.currentSessionId) return null
    return ensureSessionRuntime(state.currentSessionId, state.currentWorkspaceId)
  }

  const eventMatchesRuntime = (data: unknown, runtime: ChatSessionRuntime) => {
    const requestId = readString(data, 'request_id').trim()
    if (!requestId) return true
    if (runtime.requestId === requestId) return true
    return runtimeRequests.get(requestId)?.sessionId === runtime.sessionId
  }

  const runningSessionIds = computed(() => Object.values(sessionRuntime)
    .filter((runtime) => runtime.isGenerating)
    .map((runtime) => runtime.sessionId))
  const unreadSessionIds = computed(() => Object.values(sessionRuntime)
    .filter((runtime) => runtime.unread)
    .map((runtime) => runtime.sessionId))
  const isSessionGenerating = (sessionId: string) => Boolean(sessionRuntime[sessionId]?.isGenerating)
  const markSessionRead = (sessionId: string) => {
    const runtime = sessionRuntime[sessionId]
    if (runtime) runtime.unread = false
  }

  const rememberBlockedTtsGeneration = (generationId: string) => {
    if (!generationId) return
    blockedTtsGenerations.add(generationId)
    if (blockedTtsGenerations.size > 64) {
      const oldest = blockedTtsGenerations.values().next().value
      if (oldest) blockedTtsGenerations.delete(oldest)
    }
  }

  const hasPendingInterruptForSession = (sessionId: string) =>
    [...pendingInterrupts.values()].some((pending) => pending.sessionId === sessionId)

  const stopTtsPlaybackState = () => {
    state.isSpeaking = false
    state.isTTSPlaying = false
    if (isPetLinkEnabled()) {
      void publishCompanionRuntimeEvent({
        source: 'chat',
        activity: 'idle',
        requestId: currentRuntimeRequest?.requestId,
        interruptionEpoch: currentRuntimeRequest?.interruptionEpoch,
      })
    }
  }

  const handleAudioStarted = (event: Event) => {
    if (!isTtsEnabled()) {
      stopTtsPlaybackState()
      window.dispatchEvent(createTtsStopEvent())
      return
    }
    state.isSpeaking = true
    state.isTTSPlaying = true
    const detail = (event as CustomEvent<UnknownRecord>).detail
    const generationId = readString(detail, 'generationId')
    const sequence = readNumber(detail, 'sequence')
    if (generationId && (sequence === undefined || sequence === 0) && !reportedPlaybackGenerations.has(generationId)) {
      reportedPlaybackGenerations.add(generationId)
      if (reportedPlaybackGenerations.size > 64) {
        const oldest = reportedPlaybackGenerations.values().next().value
        if (oldest) reportedPlaybackGenerations.delete(oldest)
      }
      chatClient.getSocketClient().sendClientTiming('playback_start', {
        sessionId: state.currentSessionId,
        generationId,
      })
    }
  }

  const clearPendingUserMessage = (sessionId = state.currentSessionId) => {
    pendingUserMessages.delete(sessionId)
  }

  const initChatStore = () => {
    if (initialized) return
    initialized = true
    const socketClient = chatClient.getSocketClient()

    socketClient.on(SocketEvents.ASR_SPEECH_START, () => {
      if (!state.isGenerating && !state.isTTSPlaying && !state.isSpeaking) return
      interrupt('voice')
    })

    socketClient.on(SocketEvents.ASR_PARTIAL, (data: unknown) => {
      state.asrPartialText = readString(data, 'text')
      state.lastError = null
    })

    socketClient.on(SocketEvents.CONNECT, () => {
      state.lastError = null
    })

    socketClient.on(SocketEvents.LATENCY, (data: unknown) => {
      const snapshot = normalizeLatencySnapshot(data)
      if (!snapshot) return
      if (snapshot.kind === 'asr') state.voiceLatency.asr = snapshot
      if (snapshot.kind === 'generation') state.voiceLatency.generation = snapshot
    })

    socketClient.on(SocketEvents.INTERRUPT_ACK, (data: unknown) => {
      const requestId = readString(data, 'request_id')
      const pending = pendingInterrupts.get(requestId)
      if (pending === undefined) return
      window.clearTimeout(pending.timeoutId)
      pendingInterrupts.delete(requestId)
      const generationId = readString(data, 'generation_id')
      rememberBlockedTtsGeneration(generationId)
      socketClient.sendClientTiming('interrupt_ack', {
        sessionId: readString(data, 'session_id') || state.currentSessionId,
        generationId: generationId || undefined,
        elapsedMs: Math.max(0, performance.now() - pending.startedAt),
      })
    })

    socketClient.on(SocketEvents.DISCONNECT, () => {
      for (const pending of pendingInterrupts.values()) window.clearTimeout(pending.timeoutId)
      pendingInterrupts.clear()
      blockedTtsGenerations.clear()
      runtimeRequests.clear()
      for (const runtime of Object.values(sessionRuntime)) {
        runtime.isGenerating = false
        runtime.currentText = ''
        runtime.requestId = null
      }
      state.isGenerating = false
      state.currentText = ''
      pendingUserMessages.clear()
      state.lastError = '实时通道已断开，请确认 Python 服务和 Socket.IO 已启动'
    })

    socketClient.on(SocketEvents.ASR_FINAL, (data: unknown) => {
      const text = readString(data, 'text').trim()
      state.asrPartialText = ''
      if (!text) return
      if (
        (state.isGenerating || state.isTTSPlaying || state.isSpeaking) &&
        !hasPendingInterruptForSession(state.currentSessionId)
      ) {
        interrupt('voice')
      }
      state.messages.push({ role: 'user', content: text, timestamp: new Date().toISOString() })
      sendChat(text, { appendUser: false })
    })

    socketClient.on(SocketEvents.LLM_DELTA, (data: unknown) => {
      const token = readString(data, 'token')
      if (!token) return
      const runtime = resolveEventRuntime(data)
      if (!runtime || !eventMatchesRuntime(data, runtime)) return
      runtime.currentText += token
      runtime.isGenerating = true
      if (runtime.sessionId === state.currentSessionId) {
        state.currentText = runtime.currentText
        state.isGenerating = true
        state.lastError = null
      }
    })

    socketClient.on(SocketEvents.LLM_FINAL, (data: unknown) => {
      const runtime = resolveEventRuntime(data)
      if (!runtime || !eventMatchesRuntime(data, runtime)) return
      const text = readString(data, 'text')
      const assistantText = text || runtime.currentText
      const userMessageId = readMessageId(data, 'user_message_id')
      const assistantMessageId = readMessageId(data, 'assistant_message_id')
      const pending = pendingUserMessages.get(runtime.sessionId)
      const isActiveSession = runtime.sessionId === state.currentSessionId
      if (userMessageId !== undefined && pending && isActiveSession) {
        const message = state.messages[pending.index]
        if (
          message?.role === 'user' &&
          message.id === undefined &&
          message.content === pending.content
        ) {
          message.id = userMessageId
        }
      }
      pendingUserMessages.delete(runtime.sessionId)
      const assistantTimestamp = readString(data, 'assistant_timestamp') || readString(data, 'timestamp') || new Date().toISOString()
      const responseRequestId = readString(data, 'request_id') || runtime.requestId || ''
      const traces = responseRequestId ? pendingMessageTraces.get(responseRequestId) : undefined
      if (responseRequestId) pendingMessageTraces.delete(responseRequestId)
      const messageMetadata = traces
        ? { request_id: responseRequestId, ...traces }
        : responseRequestId ? { request_id: responseRequestId } : {}
      const assistantAlreadyVisible = assistantMessageId !== undefined && state.messages.some((message) => message.id === assistantMessageId)
      if (isActiveSession && text && !assistantAlreadyVisible) {
        state.messages.push({ id: assistantMessageId, role: 'assistant', content: text, timestamp: assistantTimestamp, ...messageMetadata })
      } else if (isActiveSession && runtime.currentText && !assistantAlreadyVisible) {
        state.messages.push({ id: assistantMessageId, role: 'assistant', content: runtime.currentText, timestamp: assistantTimestamp, ...messageMetadata })
      }
      runtime.currentText = ''
      runtime.isGenerating = false
      runtime.unread = !isActiveSession
      const runtimeRequest = responseRequestId ? runtimeRequests.get(responseRequestId) : undefined
      if (responseRequestId) runtimeRequests.delete(responseRequestId)
      runtime.requestId = null
      if (isActiveSession) {
        lastAssistantText = assistantText
        state.currentText = ''
        state.isGenerating = false
        state.lastError = null
      }
      if (isActiveSession && isPetLinkEnabled()) {
        void publishCompanionRuntimeEvent({
          source: 'chat',
          activity: 'idle',
          durationMs: 800,
          requestId: responseRequestId || runtimeRequest?.requestId,
          interruptionEpoch: runtimeRequest?.interruptionEpoch,
        })
      }
    })

    socketClient.on(SocketEvents.AGENT_RESULT, (data: unknown) => {
      const runtime = resolveEventRuntime(data)
      if (runtime && runtime.sessionId !== state.currentSessionId) return
      const envelope = normalizeActionEnvelope(data)
      const requestId = readString(data, 'request_id').trim()
      const traces = readTraceMetadata(data)
      if (traces) {
        const assistant = requestId
          ? state.messages.find((message) => message.role === 'assistant' && message.request_id === requestId)
          : state.messages.length && state.messages[state.messages.length - 1].role === 'assistant'
            ? state.messages[state.messages.length - 1]
            : undefined
        if (assistant) Object.assign(assistant, traces)
        else if (requestId) pendingMessageTraces.set(requestId, { ...(pendingMessageTraces.get(requestId) || {}), ...traces })
      }
      state.lastAgentEnvelope = envelope
      if (envelope) {
        state.agentEnvelopeTimeline.unshift({
          received_at: new Date().toISOString(),
          ...envelope,
        })
        state.agentEnvelopeTimeline = state.agentEnvelopeTimeline.slice(0, 10)
      }
      window.dispatchEvent(
        new CustomEvent('pet:agent-result', {
          detail: envelope,
        }),
      )
    })

    socketClient.on(SocketEvents.PET_CONTROL, (data: unknown) => {
      const runtime = resolveEventRuntime(data)
      if (runtime && runtime.sessionId !== state.currentSessionId) return
      if (!isPetLinkEnabled()) {
        pendingSentenceEmotionCues = []
        return
      }
      const payload = isRecord(data) && isRecord(data.pet_control)
        ? {
            ...data.pet_control,
            ...(isRecord(data.avatar_command) ? { avatar_command: data.avatar_command } : {}),
          }
        : isRecord(data)
          ? data
          : null
      if (!payload) return
      pendingSentenceEmotionCues = normalizeSentenceEmotionCues(payload.sentence_emotions)
      void publishCompanionRuntimeEvent({
        source: 'chat',
        activity: 'executing',
        durationMs: 2200,
        requestId: currentRuntimeRequest?.requestId,
        interruptionEpoch: currentRuntimeRequest?.interruptionEpoch,
      })
      window.dispatchEvent(
        new CustomEvent('pet:llm-control', {
          detail: payload,
        }),
      )
    })

    const handleTtsAudio = (data: unknown, finalEvent: boolean) => {
      const sessionId = readString(data, 'session_id') || state.currentSessionId
      const generationId = readString(data, 'generation_id')
      if (sessionId !== state.currentSessionId) return
      if (
        hasPendingInterruptForSession(sessionId) ||
        (generationId && blockedTtsGenerations.has(generationId))
      ) {
        return
      }
      const audioUrl = readString(data, 'audio_url')
      const pcmAudio = readPcmAudio(data)
      if (!audioUrl && !pcmAudio) {
        if (finalEvent && isRecord(data) && data.complete === true) {
          pendingSentenceEmotionCues = []
        }
        return
      }
      if (!isTtsEnabled()) {
        stopTtsPlaybackState()
        pendingSentenceEmotionCues = []
        window.dispatchEvent(createTtsStopEvent())
        return
      }
      const petLinkEnabled = isPetLinkEnabled()
      const segmentText = readString(data, 'text') || lastAssistantText
      const sequence = readNumber(data, 'sequence')
      const chunkIndex = readNumber(data, 'chunk_index') ?? 0
      const hasFinalField = isRecord(data) && typeof data.is_final === 'boolean'
      const isFinal = hasFinalField ? data.is_final as boolean : finalEvent
      state.isTTSPlaying = true
      state.isSpeaking = true
      if (petLinkEnabled) {
        void publishCompanionRuntimeEvent({
          source: 'chat',
          activity: 'speaking',
          requestId: currentRuntimeRequest?.requestId,
          interruptionEpoch: currentRuntimeRequest?.interruptionEpoch,
        })
      }
      const eventDetail: { text?: string; sentenceEmotionCues?: PetSentenceEmotionCue[]; visemeCues?: PetVisemeCue[]; petLinkEnabled?: boolean; generationId?: string; sequence?: number; isFinal?: boolean } = {}
      if (hasFinalField) eventDetail.isFinal = isFinal
      if (generationId) eventDetail.generationId = generationId
      if (sequence !== undefined) eventDetail.sequence = sequence
      if (!petLinkEnabled) {
        eventDetail.petLinkEnabled = false
      }
      if (segmentText) {
        eventDetail.text = segmentText
      }
      const visemeCues = normalizeVisemeCues(isRecord(data) ? data.visemes : undefined)
      if (petLinkEnabled && visemeCues.length > 0) {
        eventDetail.visemeCues = visemeCues
      }
      if (petLinkEnabled && chunkIndex === 0 && pendingSentenceEmotionCues.length > 0) {
        const matchingCues = sequence === undefined
          ? pendingSentenceEmotionCues
          : pendingSentenceEmotionCues
              .filter((cue) => cue.sentenceIndex === sequence)
              .map((cue) => ({ ...cue, sentenceIndex: 0 }))
        if (matchingCues.length > 0) eventDetail.sentenceEmotionCues = [...matchingCues]
      }
      if (pcmAudio) {
        window.dispatchEvent(new CustomEvent('pet:tts-play-pcm', {
          detail: { ...eventDetail, ...pcmAudio },
        }))
      } else if (audioUrl) {
        window.dispatchEvent(new CustomEvent('pet:tts-play-url', {
          detail: { ...eventDetail, audio_url: audioUrl },
        }))
      }
      if (isFinal) pendingSentenceEmotionCues = []
    }

    socketClient.on(SocketEvents.TTS_CHUNK, (data: unknown) => handleTtsAudio(data, false))
    socketClient.on(SocketEvents.TTS_DONE, (data: unknown) => handleTtsAudio(data, true))

    socketClient.on(SocketEvents.ERROR, (data: unknown) => {
      const message = readString(data, 'message') || readString(data, 'error') || '对话服务返回错误'
      const code = readString(data, 'code')
      const runtime = resolveEventRuntime(data)
      const isActiveSession = !runtime || runtime.sessionId === state.currentSessionId
      if (isActiveSession) state.lastError = message
      if (code.startsWith('LLM') || code.startsWith('GEN') || code.startsWith('AGENT') || code === 'chat_error') {
        if (runtime) {
          runtime.isGenerating = false
          runtime.currentText = ''
          if (runtime.requestId) runtimeRequests.delete(runtime.requestId)
          runtime.requestId = null
          clearPendingUserMessage(runtime.sessionId)
        }
        if (isActiveSession) {
          state.isGenerating = false
          state.currentText = ''
        }
      }
      if (code.startsWith('TTS')) {
        stopTtsPlaybackState()
        window.dispatchEvent(createTtsStopEvent())
      }
      if (isActiveSession) ElMessage.error(message)
    })

    if (typeof window !== 'undefined') {
      window.addEventListener('pet:audio-started', handleAudioStarted)
      window.addEventListener('pet:audio-ended', stopTtsPlaybackState)
      window.addEventListener('pet:tts-stop', stopTtsPlaybackState)
    }
  }

  onScopeDispose(() => {
    if (typeof window === 'undefined') return
    window.removeEventListener('pet:audio-started', handleAudioStarted)
    window.removeEventListener('pet:audio-ended', stopTtsPlaybackState)
    window.removeEventListener('pet:tts-stop', stopTtsPlaybackState)
  })

  const setChatOptions = (patch: Partial<ChatOptions>) => {
    Object.assign(chatOptions, normalizeChatOptions({ ...chatOptions, ...patch }))
    persistChatOptions(chatOptions)
  }

  const setTtsEnabled = (enabled: boolean) => {
    setChatOptions({ tts_enabled: enabled })
    if (!enabled) {
      stopTtsPlaybackState()
      pendingSentenceEmotionCues = []
      void petControl.stopLipSync().catch((error) => {
        console.debug('[ChatStore] failed to stop pet lip sync:', error)
      })
      window.dispatchEvent(createTtsStopEvent({ petLipSyncHandled: true }))
    }
  }

  const requestChatOptions = (override?: Partial<ChatOptions>): ChatOptions => {
    const workspaceModel = workspaceStore.activeWorkspace.default_model?.trim()
    return normalizeChatOptions({
      ...chatOptions,
      ...(workspaceModel && !chatOptions.model ? { model: workspaceModel } : {}),
      ...(override || {}),
      prompt_profile: promptProfile.value || undefined,
      prompt_mode: promptProfile.value?.mode || override?.prompt_mode || chatOptions.prompt_mode,
    })
  }

  const isPetLinkEnabled = () => chatOptions.pet_link_enabled !== false
  const isTtsEnabled = () => chatOptions.tts_enabled !== false

  const activeContextMessages = () => state.messages.slice(Math.max(0, Math.min(state.contextStartIndex, state.messages.length)))

  const setContextStartIndex = (index: number) => {
    const nextIndex = Math.max(0, Math.min(Math.round(index), state.messages.length))
    state.contextStartIndex = nextIndex
    state.currentText = ''
    state.asrPartialText = ''
    state.lastError = null
    state.lastAgentEnvelope = null
    state.agentEnvelopeTimeline = []
    pendingMessageTraces.clear()
    clearPendingUserMessage()
  }

  const setAgentTurnPreparation = (callback: AgentTurnPreparation | null) => {
    agentTurnPreparation = callback
  }

  const sendChat = (text: string, options: SendChatOptions = {}) => {
    const trimmed = text.trim()
    if (!trimmed) return false

    const socketClient = chatClient.getSocketClient()
    if (!socketClient.isConnected()) {
      const message = '实时通道未连接，请先启动 Python 服务并等待 Socket.IO 连接'
      state.lastError = message
      ElMessage.warning(message)
      return false
    }

    const shouldAppendUser = options.appendUser !== false
    const sessionId = state.currentSessionId
    const workspaceId = state.currentWorkspaceId
    let pendingUserIndex: number | null = null
    if (shouldAppendUser) {
      pendingUserIndex = state.messages.push({ role: 'user', content: trimmed, timestamp: new Date().toISOString() }) - 1
    } else {
      const lastIndex = state.messages.length - 1
      const lastMessage = state.messages[lastIndex]
      if (lastMessage?.role === 'user' && lastMessage.id === undefined && lastMessage.content === trimmed) {
        pendingUserIndex = lastIndex
      }
    }
    if (pendingUserIndex !== null) {
      pendingUserMessages.set(sessionId, {
        content: trimmed,
        index: pendingUserIndex,
      })
    }

    const requestId = createRequestId()
    const runtimeRequest: RuntimeRequest = {
      requestId,
      interruptionEpoch: getCompanionInterruptionEpoch(),
      sessionId,
      workspaceId,
    }
    runtimeRequests.set(requestId, runtimeRequest)
    currentRuntimeRequest = runtimeRequest
    const runtime = ensureSessionRuntime(sessionId, workspaceId)
    runtime.requestId = requestId
    runtime.currentText = ''
    runtime.isGenerating = true
    runtime.unread = false
    state.currentText = ''
    state.isGenerating = true
    state.lastError = null
    pendingSentenceEmotionCues = []
    lastAssistantText = ''
    if (isPetLinkEnabled()) {
      void publishCompanionRuntimeEvent({
        source: 'chat',
        activity: 'thinking',
        requestId,
        interruptionEpoch: runtimeRequest.interruptionEpoch,
      })
    }

    const contextMessages = activeContextMessages()
    const petContext = isPetLinkEnabled() ? petControlContext.value || undefined : undefined
    const requestOptions = requestChatOptions(options.chatOptions)
    const dispatchAgentChat = () => {
      const pendingRuntime = sessionRuntime[sessionId]
      if (pendingRuntime?.requestId !== requestId || !pendingRuntime.isGenerating) return
      socketClient.sendAgentChat(contextMessages, sessionId, petContext, requestId, workspaceId, requestOptions)
    }
    const prepareTurn = agentTurnPreparation
    if (!prepareTurn) {
      dispatchAgentChat()
      return true
    }
    void Promise.resolve()
      .then(prepareTurn)
      .catch((error) => logger.warn('Agent turn preparation failed; continuing without it:', error))
      .finally(dispatchAgentChat)
    return true
  }

  const applyRealtimeInputPartial = (text: string) => {
    state.asrPartialText = text.trim()
    state.lastError = null
  }

  const applyRealtimeAssistantDelta = (text: string) => {
    state.currentText = text
    state.asrPartialText = ''
    state.isGenerating = true
    state.lastError = null
  }

  const setRealtimeRecording = (recording: boolean) => {
    state.isRecording = recording
    if (recording) {
      currentRealtimeRuntimeRequest = {
        requestId: `realtime_${createRequestId()}`,
        interruptionEpoch: getCompanionInterruptionEpoch(),
      }
      state.asrPartialText = ''
      state.currentText = ''
      state.lastError = null
    }
  }

  const setRealtimePlayback = (playing: boolean) => {
    state.isSpeaking = playing
    state.isTTSPlaying = playing
    if (isPetLinkEnabled()) {
      void publishCompanionRuntimeEvent({
        source: 'chat',
        activity: playing ? 'speaking' : 'idle',
        requestId: currentRealtimeRuntimeRequest?.requestId,
        interruptionEpoch: currentRealtimeRuntimeRequest?.interruptionEpoch,
      })
    }
  }

  const completeRealtimeTurn = async (turn: RealtimeTurnRecord) => {
    const userText = turn.userText.trim()
    const assistantText = turn.assistantText.trim()
    if (!userText || !assistantText) return

    const timestamp = new Date().toISOString()
    const userIndex = state.messages.push({
      role: 'user',
      content: userText,
      timestamp,
    }) - 1
    const assistantIndex = state.messages.push({
      role: 'assistant',
      content: assistantText,
      timestamp,
    }) - 1
    lastAssistantText = assistantText
    state.currentText = ''
    state.asrPartialText = ''
    state.isGenerating = false
    state.lastError = null
    if (isPetLinkEnabled()) {
      void publishCompanionRuntimeEvent({
        source: 'chat',
        activity: 'idle',
        durationMs: 800,
        requestId: currentRealtimeRuntimeRequest?.requestId,
        interruptionEpoch: currentRealtimeRuntimeRequest?.interruptionEpoch,
      })
    }

    try {
      const saved = await requestJson<RealtimeTranscriptResponse>(`${API_ORIGIN}/api/realtime/transcript`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: turn.workspaceId,
          session_id: turn.sessionId,
          turn_id: turn.turnId,
          user_text: userText,
          assistant_text: assistantText,
        }),
      })
      const userMessage = state.messages[userIndex]
      const assistantMessage = state.messages[assistantIndex]
      if (userMessage && saved.user_message?.id !== undefined) {
        userMessage.id = saved.user_message.id
        userMessage.timestamp = saved.user_message.timestamp || userMessage.timestamp
      }
      if (assistantMessage && saved.assistant_message?.id !== undefined) {
        assistantMessage.id = saved.assistant_message.id
        assistantMessage.timestamp = saved.assistant_message.timestamp || assistantMessage.timestamp
      }
    } catch (error) {
      console.warn('[ChatStore] failed to persist realtime transcript:', error)
    }
  }

  const setRealtimeError = (message: string) => {
    state.lastError = message
    state.isGenerating = false
    state.currentText = ''
    state.asrPartialText = ''
    setRealtimeRecording(false)
    setRealtimePlayback(false)
  }

  const interrupt = (source: 'manual' | 'voice' = 'manual') => {
    void publishCompanionInterrupt('chat')
    window.dispatchEvent(new CustomEvent('pet:realtime-interrupt', { detail: { source } }))
    const socketClient = chatClient.getSocketClient()
    if (socketClient.isConnected()) {
      const requestId = `interrupt_${createRequestId()}`
      const sessionId = state.currentSessionId
      const timeoutId = window.setTimeout(() => pendingInterrupts.delete(requestId), 2000)
      pendingInterrupts.set(requestId, {
        startedAt: performance.now(),
        sessionId,
        timeoutId,
      })
      socketClient.sendInterrupt(state.currentSessionId, requestId, source)
    } else {
      ElMessage.info('当前未连接 Socket.IO，已仅在前端中断显示')
    }

    state.isGenerating = false
    state.currentText = ''
    const runtime = ensureSessionRuntime(state.currentSessionId, state.currentWorkspaceId)
    runtime.isGenerating = false
    runtime.currentText = ''
    if (runtime.requestId) runtimeRequests.delete(runtime.requestId)
    runtime.requestId = null
    clearPendingUserMessage(runtime.sessionId)
    stopTtsPlaybackState()
    pendingSentenceEmotionCues = []
    void petControl.stopLipSync({ interrupted: true }).catch((error) => {
      console.debug('[ChatStore] failed to stop pet lip sync:', error)
    })
    window.dispatchEvent(createTtsStopEvent({ interrupted: true, petLipSyncHandled: true }))
  }

  const setPetControlContext = (context: PetControlContextPayload) => {
    petControlContext.value = context
  }

  const setCompanionPersonaPrompt = (prompt: string | null) => {
    companionPersonaPrompt.value = prompt?.trim() || null
  }

  const setPromptProfile = (profile: ChatPromptProfile | null) => {
    promptProfile.value = profile ? normalizePromptProfile(profile) ?? null : null
  }

  const setWorkspaceContext = (workspaceId: string, sessionId: string) => {
    historyLoadEpoch += 1
    state.currentWorkspaceId = workspaceId
    state.currentSessionId = sessionId
    const runtime = ensureSessionRuntime(sessionId, workspaceId)
    state.currentText = runtime.currentText
    state.isGenerating = runtime.isGenerating
    state.asrPartialText = ''
    state.lastError = null
    currentRuntimeRequest = runtime.requestId ? runtimeRequests.get(runtime.requestId) || null : null
    markSessionRead(sessionId)
  }

  const loadHistory = async (sessionId: string, workspaceId?: string) => {
    const requestEpoch = ++historyLoadEpoch
    state.currentSessionId = sessionId
    if (workspaceId) state.currentWorkspaceId = workspaceId
    const payload = await requestJson<{ history: ChatHistoryRecord[] }>(
      withWorkspaceQuery(`${CONTROL_ORIGIN}/api/history/${encodeURIComponent(sessionId)}?limit=50`, workspaceId),
    )
    if (requestEpoch !== historyLoadEpoch || state.currentSessionId !== sessionId) return
    state.messages = Array.isArray(payload.history)
      ? payload.history.map((message) => ({
          id: message.id ?? undefined,
          role: message.role,
          content: message.content,
          timestamp: message.timestamp || null,
          ...(message.request_id ? { request_id: message.request_id } : {}),
          ...(message.tool_trace ? { tool_trace: message.tool_trace } : {}),
          ...(message.memory_trace ? { memory_trace: message.memory_trace } : {}),
          ...(message.agentSteps ? { agentSteps: message.agentSteps } : {}),
          ...(message.memorySources ? { memorySources: message.memorySources } : {}),
        }))
      : []
    state.contextStartIndex = 0
    const runtime = ensureSessionRuntime(sessionId, workspaceId || state.currentWorkspaceId)
    state.currentText = runtime.currentText
    state.asrPartialText = ''
    state.isGenerating = runtime.isGenerating
    state.lastError = null
    state.lastAgentEnvelope = null
    state.agentEnvelopeTimeline = []
    pendingMessageTraces.clear()
    markSessionRead(sessionId)
  }

  const appendLocalAdvice = (text: string, source = 'behavior'): ChatAdviceItem | null => {
    const content = text.trim()
    if (!content) return null
    const item = {
      id: createAdviceId(),
      content,
      createdAt: new Date().toISOString(),
      source,
    }
    state.adviceFeed.unshift({
      ...item,
    })
    state.adviceFeed = state.adviceFeed.slice(0, 20)
    return item
  }

  const appendAdviceMessage = (text: string) => {
    const content = text.trim()
    if (!content) return
    state.messages.push({ role: 'assistant', content: `[建议] ${content}`, timestamp: new Date().toISOString() })
  }

  const dismissAdvice = (adviceId: string) => {
    state.adviceFeed = state.adviceFeed.filter((advice) => advice.id !== adviceId)
  }

  const promoteAdviceToMessage = (adviceId: string) => {
    const item = state.adviceFeed.find((advice) => advice.id === adviceId)
    if (!item) return false
    appendAdviceMessage(item.content)
    dismissAdvice(adviceId)
    return true
  }

  const clearAdviceFeed = () => {
    state.adviceFeed = []
  }

  const notifications = ref<Array<{ id: string; text: string; time: string }>>([])

  const addNotification = (text: string) => {
    notifications.value.unshift({ id: Date.now().toString(), text, time: new Date().toLocaleTimeString() })
    notifications.value = notifications.value.slice(0, 20)
  }

  const getAgentEnvelopeTrace = () => state.agentEnvelopeTimeline

  const removeLocalMessageAt = (index: number) => {
    if (index >= 0 && index < state.messages.length) {
      state.messages.splice(index, 1)
      if (index < state.contextStartIndex) {
        state.contextStartIndex = Math.max(0, state.contextStartIndex - 1)
      } else if (state.contextStartIndex > state.messages.length) {
        state.contextStartIndex = state.messages.length
      }
    }
  }

  const deleteMessage = async (index: number, workspaceId?: string) => {
    const message = state.messages[index]
    if (!message) return false
    if (message.id !== undefined && message.id !== null && String(message.id).trim()) {
      await requestJson<{ status: string }>(withWorkspaceQuery(`${CONTROL_ORIGIN}/api/messages/${encodeURIComponent(String(message.id))}`, workspaceId), { method: 'DELETE' })
    }
    removeLocalMessageAt(index)
    return true
  }

  const updateMessage = async (index: number, content: string, workspaceId?: string) => {
    const message = state.messages[index]
    const trimmed = content.trim()
    if (!message || !trimmed) return false
    if (message.id !== undefined && message.id !== null && String(message.id).trim()) {
      const payload = await requestJson<{ status: string; message?: ChatHistoryRecord }>(withWorkspaceQuery(`${CONTROL_ORIGIN}/api/messages/${encodeURIComponent(String(message.id))}`, workspaceId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: trimmed }),
      })
      if (payload.message?.timestamp) {
        message.timestamp = payload.message.timestamp
      }
    }
    message.content = trimmed
    return true
  }

  const trimMessagesAfter = async (index: number, workspaceId?: string) => {
    const message = state.messages[index]
    if (!message) return 0
    const trailingMessages = state.messages.slice(index + 1)
    const persistedRemoved = trailingMessages.filter((item) => item.id !== undefined && item.id !== null).length
    const hasPersistedBoundary = message.id !== undefined && message.id !== null && String(message.id).trim()
    if (hasPersistedBoundary) {
      await requestJson<{ status: string; deleted_count: number }>(withWorkspaceQuery(`${CONTROL_ORIGIN}/api/messages/${encodeURIComponent(String(message.id))}/after`, workspaceId), { method: 'DELETE' })
    }
    state.messages.splice(index + 1)
    if (state.contextStartIndex > state.messages.length) {
      state.contextStartIndex = state.messages.length
    }
    return persistedRemoved
  }

  const regenerateFromMessage = async (index: number, workspaceId?: string) => {
    const message = state.messages[index]
    if (!message || message.role !== 'user') return 0
    const persistedRemoved = await trimMessagesAfter(index, workspaceId)
    sendChat(message.content, { appendUser: false })
    return persistedRemoved
  }

  const clearConversationMessages = async (workspaceId?: string) => {
    if (!state.currentSessionId) {
      clearLocalMessages()
      return false
    }
    if (!state.messages.some((message) => message.id !== undefined && message.id !== null)) {
      clearLocalMessages()
      return false
    }
    await requestJson<{ status: string }>(withWorkspaceQuery(`${CONTROL_ORIGIN}/api/sessions/${encodeURIComponent(state.currentSessionId)}/messages`, workspaceId), { method: 'DELETE' })
    clearLocalMessages()
    return true
  }

  const copyMessage = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      ElMessage.success('已复制到剪贴板')
    } catch {
      ElMessage.warning('复制失败')
    }
  }

  const transcriptText = () => state.messages
    .map((message) => `${message.role === 'user' ? '你' : message.role === 'assistant' ? '結崎' : '系统'}：${message.content}`)
    .join('\n\n')

  const copyTranscript = async () => {
    const text = transcriptText()
    if (!text) {
      ElMessage.info('暂无可复制的对话')
      return
    }
    await copyMessage(text)
  }

  const copyLastAssistantMessage = async () => {
    const lastAssistant = [...state.messages].reverse().find((message) => message.role === 'assistant')
    if (!lastAssistant) {
      ElMessage.info('暂无助手回复可复制')
      return
    }
    await copyMessage(lastAssistant.content)
  }

  const clearLocalMessages = () => {
    state.messages = []
    state.contextStartIndex = 0
    state.currentText = ''
    state.asrPartialText = ''
    state.lastError = null
    state.lastAgentEnvelope = null
    state.agentEnvelopeTimeline = []
    pendingMessageTraces.clear()
    clearPendingUserMessage()
  }

  const clearContext = () => {
    const timestamp = new Date().toISOString()
    state.messages.push({
      role: 'system',
      content: '已清理上下文。之后发送的消息只会携带从这里开始的新上下文。',
      timestamp,
    })
    state.contextStartIndex = state.messages.length
    state.currentText = ''
    state.asrPartialText = ''
    state.lastError = null
    state.lastAgentEnvelope = null
    state.agentEnvelopeTimeline = []
    clearPendingUserMessage()
  }

  const translateText = async (text: string, targetLanguage?: string) => {
    const trimmed = text.trim()
    if (!trimmed) return ''
    const payload = await requestJson<{ translated_text: string }>(`${CONTROL_ORIGIN}/api/chat/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: trimmed,
        target_language: targetLanguage || chatOptions.translation_target || DEFAULT_CHAT_OPTIONS.translation_target,
        chat_options: requestChatOptions(),
      }),
    })
    return payload.translated_text || ''
  }

  return {
    state,
    chatOptions,
    sessionRuntime,
    runningSessionIds,
    unreadSessionIds,
    isSessionGenerating,
    markSessionRead,
    initChatStore,
    sendChat,
    applyRealtimeInputPartial,
    applyRealtimeAssistantDelta,
    setRealtimeRecording,
    setRealtimePlayback,
    completeRealtimeTurn,
    setRealtimeError,
    setChatOptions,
    setTtsEnabled,
    activeContextMessages,
    setContextStartIndex,
    setAgentTurnPreparation,
    interrupt,
    setPetControlContext,
    setCompanionPersonaPrompt,
    setPromptProfile,
    setWorkspaceContext,
    loadHistory,
    appendLocalAdvice,
    appendAdviceMessage,
    promoteAdviceToMessage,
    dismissAdvice,
    clearAdviceFeed,
    getAgentEnvelopeTrace,
    deleteMessage,
    updateMessage,
    trimMessagesAfter,
    regenerateFromMessage,
    clearConversationMessages,
    copyMessage,
    transcriptText,
    copyTranscript,
    copyLastAssistantMessage,
    clearLocalMessages,
    clearContext,
    translateText,
    notifications,
    addNotification,
  }
})

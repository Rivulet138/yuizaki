import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RealtimeVoiceScope } from '@/audio/realtime-voice'

const harness = vi.hoisted(() => ({
  mounted: [] as Array<() => void>,
  listeners: new Map<string, (payload: unknown) => void>(),
  continuous: true,
  microphone: true,
  identity: undefined as Partial<RealtimeVoiceScope> | undefined,
  store: {
    state: { currentWorkspaceId: 'workspace', currentSessionId: 'session', isGenerating: true },
    chatOptions: { response_mode: 'pipeline', pet_link_enabled: false },
    setRealtimeStatus: vi.fn(),
    setRealtimeRecording: vi.fn(),
    setPetControlContext: vi.fn(),
  },
}))

vi.mock('vue', () => ({
  onMounted: (callback: () => void) => harness.mounted.push(callback),
  onUnmounted: vi.fn(),
  watch: vi.fn(),
}))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn() } }))
vi.mock('@/audio/audio-capture', () => ({ audioCapture: { getStatus: () => ({}) } }))
vi.mock('@/audio/realtime-voice', () => ({
  realtimeVoiceSession: {
    on: (event: string, callback: (payload: unknown) => void) => {
      harness.listeners.set(event, callback)
      return () => harness.listeners.delete(event)
    },
    isContinuousMode: () => harness.continuous,
    isMicrophoneActive: () => harness.microphone,
    getCurrentTurnIdentity: () => harness.identity,
  },
}))
vi.mock('@/pet-sentence-emotion-scheduler', () => ({ PetSentenceEmotionScheduler: class {} }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => harness.store }))
vi.mock('@/utils/petControl', () => ({
  petControl: {
    getCatalog: async () => ({ models: [] }),
    getAvatarCapabilities: async () => null,
  },
}))
vi.mock('@/api/client', () => ({
  chatClient: { getSocketClient: () => ({ isConnected: () => false }) },
  shortcutClient: { on: vi.fn(), off: vi.fn() },
  systemClient: { beginVoiceDiagnosticsRun: async (runId: string) => ({ run_id: runId }) },
}))
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('../runtime/companionRuntime', () => ({
  getCompanionInterruptionEpoch: () => 1,
  publishCompanionJobEvent: vi.fn(),
  publishCompanionRuntimeEvent: vi.fn(),
}))

import { useVoiceConversationBridge } from './useVoiceConversationBridge'

describe('ready realtime recording identity', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    harness.mounted.length = 0
    harness.listeners.clear()
    harness.continuous = true
    harness.microphone = true
    harness.identity = { requestId: 'request', turnId: 'turn', generationId: 'generation', interruptionEpoch: 1 }
    harness.store.state.isGenerating = true
    vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn() })
    useVoiceConversationBridge()
    harness.mounted.forEach((callback) => callback())
  })

  afterEach(() => vi.unstubAllGlobals())

  it('continues recording with a complete turn identity', () => {
    harness.listeners.get('status')?.({ status: 'ready' })
    expect(harness.store.setRealtimeRecording).toHaveBeenCalledWith(true, harness.identity)
    expect(harness.store.state.isGenerating).toBe(false)
  })

  it.each(['requestId', 'turnId', 'generationId', 'interruptionEpoch'] as const)(
    'does not publish an incomplete identity without %s', (field) => {
      delete harness.identity?.[field]
      harness.listeners.get('status')?.({ status: 'ready' })
      expect(harness.store.setRealtimeRecording).toHaveBeenCalledWith(false, undefined)
    },
  )

  it.each(['continuous', 'microphone'] as const)('stops recording when %s is disabled', (field) => {
    harness[field] = false
    harness.listeners.get('status')?.({ status: 'ready' })
    expect(harness.store.setRealtimeRecording).toHaveBeenCalledWith(false, undefined)
  })
})

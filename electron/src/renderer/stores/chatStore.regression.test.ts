import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SocketEvents } from '../../shared/runtimeProtocol'
import { useChatStore } from './chatStore'

const mocks = vi.hoisted(() => ({
  listeners: new Map<string, (data: unknown) => void>(),
  requestJson: vi.fn<(url: string, options?: RequestInit) => Promise<unknown>>(),
  sendAgentChat: vi.fn(),
  sendInterrupt: vi.fn(),
}))

vi.mock('element-plus', () => ({ ElMessage: { warning: vi.fn(), error: vi.fn(), info: vi.fn() } }))
vi.mock('@/utils/petControl', () => ({ petControl: { stopLipSync: vi.fn(async () => undefined) } }))
vi.mock('@/api/client', () => ({
  chatClient: {
    getSocketClient: () => ({
      on: (event: string, listener: (data: unknown) => void) => mocks.listeners.set(event, listener),
      isConnected: () => true,
      sendAgentChat: mocks.sendAgentChat,
      sendInterrupt: mocks.sendInterrupt,
      sendClientTiming: vi.fn(),
    }),
  },
}))
vi.mock('@/api/clients/http-client', () => ({
  API_ORIGIN: 'http://localhost',
  CONTROL_ORIGIN: 'http://localhost',
  requestJson: mocks.requestJson,
}))
vi.mock('../net/socketClient', () => import('../../shared/runtimeProtocol'))
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('./workspaceStore', () => ({ useWorkspaceStore: () => ({ activeWorkspace: {} }) }))
vi.mock('@/app/runtime/companionRuntime', () => ({
  getCompanionInterruptionEpoch: () => 0,
  publishCompanionInterrupt: vi.fn(),
  publishCompanionRuntimeEvent: vi.fn(),
}))

const identity = {
  requestId: 'request-1',
  generationId: 'generation-1',
  turnId: 'turn-1',
  interruptionEpoch: 0,
}
const eventEnvelope = {
  envelope_version: 1,
  request_id: identity.requestId,
  generation_id: identity.generationId,
  turn_id: identity.turnId,
  interruption_epoch: identity.interruptionEpoch,
  session_id: 'default',
}
const realtimeTurn = {
  ...identity,
  userText: 'Hello',
  assistantText: 'Hi',
  model: 'test-model',
  workspaceId: 'default',
  sessionId: 'default',
}

describe('chat store boundary regressions', () => {
  let pinia: ReturnType<typeof createPinia>
  let scope: ReturnType<typeof effectScope>
  let store: ReturnType<typeof useChatStore>

  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listeners.clear()
    mocks.sendAgentChat.mockReturnValue({ status: 'accepted' })
    mocks.sendInterrupt.mockReturnValue({ status: 'accepted' })
    mocks.requestJson.mockResolvedValue({ status: 'ok' })
    vi.stubGlobal('window', Object.assign(new EventTarget(), {
      localStorage: { getItem: () => null, setItem: vi.fn() },
      setTimeout,
      clearTimeout,
    }))
    pinia = createPinia()
    setActivePinia(pinia)
    store = useChatStore()
    store.setTtsEnabled(true)
    scope = effectScope()
    scope.run(() => store.initChatStore())
  })

  afterEach(() => {
    scope.stop()
    disposePinia(pinia)
    vi.unstubAllGlobals()
  })

  const emit = (event: string, data: unknown) => {
    const listener = mocks.listeners.get(event)
    expect(listener).toBeDefined()
    listener?.(data)
  }

  const emitPlaybackEvent = (event: string, detail: Record<string, unknown> = {}) => {
    window.dispatchEvent(new CustomEvent(event, { detail }))
  }

  const startRequest = () => {
    expect(store.sendChat('Hello', {
      envelope: { version: 1, ...identity },
      chatOptions: { tts_enabled: false },
    })).toBe(true)
  }

  it.each(['delete', 'trim', 'regenerate', 'clear'] as const)('keeps the newly selected conversation intact after a late %s response', async (operation) => {
    store.setWorkspaceContext('workspace-a', 'session-a')
    store.state.messages = [
      { id: 1, role: 'user', content: 'A question' },
      { id: 2, role: 'assistant', content: 'A answer' },
    ]
    let resolve!: (value: unknown) => void
    mocks.requestJson.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const pending = operation === 'delete' ? store.deleteMessage(0, 'workspace-a')
      : operation === 'trim' ? store.trimMessagesAfter(0, 'workspace-a')
      : operation === 'regenerate' ? store.regenerateFromMessage(0, 'workspace-a')
      : store.clearConversationMessages('workspace-a')
    store.setWorkspaceContext('workspace-b', 'session-b')
    store.state.messages = [
      { id: 3, role: 'user', content: 'B question' },
      { id: 4, role: 'assistant', content: 'B answer' },
    ]
    resolve({ status: 'ok', deleted_count: 1 })
    await pending
    expect(store.state.messages.map(message => message.content)).toEqual(['B question', 'B answer'])
    expect(mocks.sendAgentChat).not.toHaveBeenCalled()
  })

  it.each([true, false])('sends all role card fields with enabled=%s after setPromptProfile', (enabled) => {
    const roleCard = {
      enabled,
      name: 'Yuizaki',
      description: '  A local companion.\nHer story.  ',
      personality: 'Curious',
      scenario: 'At home',
      instructions: 'Keep answers clear.',
      firstMessage: 'Hello, {{user}}!',
      exampleDialogue: '<START>\n{{user}}: Hi\n{{char}}: Hello!\n',
      alternateGreetings: ['Another greeting'],
      greetingIndex: 0,
    }
    store.setPromptProfile({ mode: 'daily', roleCard })

    startRequest()

    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
    const requestOptions = mocks.sendAgentChat.mock.calls[0]?.[5]
    expect(requestOptions).toMatchObject({ prompt_mode: 'daily', prompt_profile: { mode: 'daily' } })
    expect(requestOptions.prompt_profile.roleCard).toEqual(roleCard)
    expect(requestOptions.tts_enabled).toBe(false)
  })

  it('does not transmit imported card metadata or extension instructions in the chat profile', () => {
    store.setPromptProfile({ roleCard: {
      name: 'A', enabled: true, firstMessage: 'Primary', alternateGreetings: ['Alternate'], greetingIndex: 0,
      sourceCard: { data: { creator_notes: 'Private author note', extensions: { executable: 'inert' } } },
    } } as any)
    startRequest()
    const sent = mocks.sendAgentChat.mock.calls[0]?.[5]?.prompt_profile?.roleCard
    expect(sent.alternateGreetings).toEqual(['Alternate'])
    expect(sent.greetingIndex).toBe(0)
    expect(sent).not.toHaveProperty('sourceCard')
    expect(JSON.stringify(sent)).not.toContain('Private author note')
  })

  it('sends old role cards without requiring description or exampleDialogue', () => {
    const roleCard = {
      enabled: false, name: 'Legacy', personality: 'Kind', scenario: 'Town',
      instructions: 'Be helpful.', firstMessage: 'Welcome!',
    }
    store.setPromptProfile({ roleCard })

    startRequest()

    const sentRoleCard = mocks.sendAgentChat.mock.calls[0]?.[5]?.prompt_profile?.roleCard
    expect(sentRoleCard).toEqual({ ...roleCard, description: undefined, exampleDialogue: undefined })
    expect(JSON.parse(JSON.stringify(sentRoleCard))).toEqual(roleCard)
  })

  it.each(['offline', 'rejected'])('keeps the local message and clears busy when transport returns %s', (status) => {
    mocks.sendAgentChat.mockReturnValueOnce({ status })
    expect(store.sendChat('unsent draft')).toBe(false)
    expect(store.state.isGenerating).toBe(false)
    expect(store.state.messages.at(-1)?.content).toBe('unsent draft')
    expect(store.runningSessionIds).toEqual([])
  })

  it('restores a failed draft once without deleting the local message', () => {
    const restore = vi.fn()
    expect(store.sendChat('failed draft', { envelope: { version: 1, ...identity }, onFailure: restore })).toBe(true)
    emit(SocketEvents.ERROR, { ...eventEnvelope, code: 'AGENT_FAILED', message: 'upstream failed' })
    emit(SocketEvents.ERROR, { ...eventEnvelope, code: 'AGENT_FAILED', message: 'duplicate error' })
    expect(restore).toHaveBeenCalledTimes(1)
    expect(store.state.messages[0]?.content).toBe('failed draft')
    expect(store.state.isGenerating).toBe(false)
  })

  it('clears old subtitles on a session switch and ignores late playback for that generation', () => {
    startRequest()
    emitPlaybackEvent('pet:audio-started', { generationId: identity.generationId, sessionId: 'default', segmentId: 1, text: 'old speech' })
    store.setWorkspaceContext('default', 'session-b')
    expect(store.state.ttsPlaybackText).toBe('')
    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.messages).toEqual([])
    emitPlaybackEvent('pet:audio-started', { generationId: identity.generationId, sessionId: 'default', segmentId: 2, text: 'late old speech' })
    expect(store.state.ttsPlaybackText).toBe('')
    emitPlaybackEvent('pet:audio-started', { generationId: 'generation-b', sessionId: 'session-b', segmentId: 3, text: 'new speech' })
    emitPlaybackEvent('pet:audio-ended', { generationId: identity.generationId })
    expect(store.state.ttsPlaybackText).toBe('new speech')
    expect(store.state.isTTSPlaying).toBe(true)
  })

  it('restores a background session draft on disconnect without moving its text into the active session', () => {
    const restore = vi.fn()
    store.sendChat('background draft', { onFailure: restore })
    store.clearLocalMessages()
    store.setWorkspaceContext('default', 'session-b')
    emit(SocketEvents.DISCONNECT, {})
    expect(restore).toHaveBeenCalledTimes(1)
    expect(store.state.currentSessionId).toBe('session-b')
    expect(store.state.currentText).toBe('')
    expect(store.state.ttsPlaybackText).toBe('')
  })

  it('binds delayed transcript persistence to the originating message objects', async () => {
    let save!: (value: unknown) => void
    mocks.requestJson.mockImplementationOnce(() => new Promise(resolve => { save = resolve }))
    store.setRealtimeRecording(true, identity)
    const saving = store.completeRealtimeTurn(realtimeTurn)
    store.setWorkspaceContext('default', 'session-b')
    store.state.messages.push({ role: 'user', content: 'B user' }, { role: 'assistant', content: 'B assistant' })
    save({ user_message: { id: 'A-user' }, assistant_message: { id: 'A-assistant' } })
    await saving
    expect(store.state.messages.map(message => message.id)).toEqual([undefined, undefined])
  })

  it('does not stop active speech when a background session reports a TTS error', () => {
    store.sendChat('A turn', { envelope: { version: 1, ...identity } })
    store.setWorkspaceContext('default', 'session-b')
    emitPlaybackEvent('pet:audio-started', { generationId: 'B-generation', sessionId: 'session-b', segmentId: 9, text: 'B speech' })
    const stop = vi.fn()
    window.addEventListener('pet:tts-stop', stop)
    emit(SocketEvents.ERROR, { ...eventEnvelope, code: 'TTS_FAILED', message: 'A audio failed' })
    expect(stop).not.toHaveBeenCalled()
    expect(store.state.ttsPlaybackText).toBe('B speech')
    expect(store.state.isTTSPlaying).toBe(true)
  })

  it('keeps the current draft after a rejected send without including its duplicate in the next payload', () => {
    mocks.sendAgentChat.mockReturnValueOnce({ status: 'offline' })
    expect(store.sendChat('same draft')).toBe(false)
    expect(store.sendChat('same draft')).toBe(true)
    const messages = mocks.sendAgentChat.mock.calls.at(-1)?.[0] as Array<{ content: string }>
    expect(messages.filter(message => message.content === 'same draft')).toHaveLength(1)
  })

  it('preserves a new reply when an older history snapshot finishes loading', async () => {
    let release!: (value: unknown) => void
    mocks.requestJson.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const history = store.loadHistory('default', 'default')
    startRequest()
    emit(SocketEvents.LLM_FINAL, { ...eventEnvelope, sequence: 0, text: 'new reply', tts_expected: false, user_message_id: 1, assistant_message_id: 2 })
    release({ history: [{ id: 0, role: 'assistant', content: 'older history' }] })
    await history
    expect(store.state.messages.map(message => message.content)).toEqual(['older history', 'Hello', 'new reply'])
  })

  it('filters unsupported action types while preserving supported actions and absent-type replies', () => {
    startRequest()
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    emit(SocketEvents.AGENT_RESULT, {
      ...eventEnvelope,
      reply: 'Hi',
      actions: [
        { type: 'reply', content: 'Hi', schema_version: 'v1', source: 'agent' },
        { type: 'pet_control', payload: { emotion: 'happy' } },
        { type: 'tool_trace', payload: [] },
        { content: 'Legacy reply' },
        { type: 'unsupported', content: 'Invalid' },
        { type: null },
        { type: 42 },
        { type: false },
        { type: '' },
        null,
        [],
      ],
    })

    expect(store.state.lastAgentEnvelope?.actions).toEqual([
      { type: 'reply', content: 'Hi', schema_version: 'v1', source: 'agent' },
      { type: 'pet_control', payload: { emotion: 'happy' } },
      { type: 'tool_trace', payload: [] },
      { type: 'reply', content: 'Legacy reply' },
    ])
    expect(store.state.agentEnvelopeTimeline[0]?.actions).toEqual(store.state.lastAgentEnvelope?.actions)
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: 'pet:agent-result', detail: store.state.lastAgentEnvelope,
    }))
  })

  it('keeps realtime memory traces when excluding actions outside the shared action contract', async () => {
    const memory = [{ content: 'Remembered preference' }]
    store.setRealtimeRecording(true, identity)
    await store.completeRealtimeTurn({
      ...realtimeTurn,
      actionEnvelope: { actions: [{ type: 'memory_trace', payload: memory }] },
    })

    expect(store.state.lastAgentEnvelope?.actions).toEqual([])
    expect(store.state.messages[1]?.memory_trace).toEqual(memory)
    const body = mocks.requestJson.mock.calls[0]?.[1]?.body
    if (typeof body !== 'string') throw new Error('Expected a JSON transcript body')
    const payload: unknown = JSON.parse(body)
    expect(payload).toMatchObject({ memory_trace: memory })
  })

  it.each(['envelope_version', 'request_id', 'generation_id', 'turn_id', 'interruption_epoch'])(
    'ignores completed-request events missing %s',
    (field) => {
      startRequest()
      emit(SocketEvents.LLM_FINAL, { ...eventEnvelope, sequence: 0, text: 'Hi', tts_expected: false })
      expect(store.sessionRuntime.default.requestId).toBeNull()
      const incomplete = { ...eventEnvelope, [field]: undefined, reply: 'Invalid', actions: [] }
      const dispatch = vi.spyOn(window, 'dispatchEvent')

      expect(() => emit(SocketEvents.AGENT_RESULT, incomplete)).not.toThrow()
      expect(store.state.lastAgentEnvelope).toBeNull()
      expect(store.state.agentEnvelopeTimeline).toEqual([])
      expect(dispatch).not.toHaveBeenCalled()

      emit(SocketEvents.AGENT_RESULT, { ...eventEnvelope, reply: 'Hi', actions: [] })
      expect(store.state.lastAgentEnvelope?.reply).toBe('Hi')
      expect(store.state.agentEnvelopeTimeline).toHaveLength(1)
    },
  )

  it('rejects completed-request events with unknown or mismatched identities', () => {
    startRequest()
    emit(SocketEvents.LLM_FINAL, { ...eventEnvelope, sequence: 0, text: 'Hi', tts_expected: false })
    for (const mismatch of [
      { request_id: 'unknown' }, { generation_id: 'stale' }, { turn_id: 'stale' },
      { interruption_epoch: 1 }, { session_id: 'other' }, { envelope_version: 2 },
    ]) {
      emit(SocketEvents.AGENT_RESULT, { ...eventEnvelope, ...mismatch, reply: 'Invalid', actions: [] })
    }
    expect(store.state.lastAgentEnvelope).toBeNull()
    expect(store.state.agentEnvelopeTimeline).toEqual([])
  })

  it.each([null, undefined, '', '   ', Number.NaN])('does not assign invalid persisted message IDs (%s)', async (id) => {
    mocks.requestJson.mockResolvedValue({
      status: 'ok',
      user_message: { id, timestamp: 'saved-user-time' },
      assistant_message: { id, timestamp: 'saved-assistant-time' },
    })
    store.setRealtimeRecording(true, identity)
    await store.completeRealtimeTurn(realtimeTurn)

    expect(store.state.messages).toHaveLength(2)
    expect(store.state.messages.map((message) => message.id)).toEqual([undefined, undefined])
    expect(store.state.messages.every((message) => message.timestamp !== 'saved-user-time'
      && message.timestamp !== 'saved-assistant-time')).toBe(true)
  })

  it('accepts persisted numeric zero and string IDs with their timestamps', async () => {
    mocks.requestJson.mockResolvedValue({
      status: 'ok',
      user_message: { id: 0, timestamp: 'saved-user-time' },
      assistant_message: { id: 'assistant-1', timestamp: 'saved-assistant-time' },
    })
    store.setRealtimeRecording(true, identity)
    await store.completeRealtimeTurn(realtimeTurn)

    expect(store.state.messages.map(({ id, timestamp }) => ({ id, timestamp }))).toEqual([
      { id: 0, timestamp: 'saved-user-time' },
      { id: 'assistant-1', timestamp: 'saved-assistant-time' },
    ])
  })

  it('interrupts the previous generation before starting a new text turn', () => {
    startRequest()
    store.state.isTTSPlaying = true

    expect(store.sendChat('Follow-up', {
      envelope: { version: 1, ...identity, requestId: 'request-2', generationId: 'generation-2', turnId: 'turn-2' },
      chatOptions: { tts_enabled: false },
    })).toBe(true)
    expect(mocks.sendInterrupt).toHaveBeenCalledTimes(1)
    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(2)
  })

  it('keeps the generation text when a later audio segment has no text', () => {
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-1',
      segmentId: 1,
      sequence: 0,
      utteranceId: 'generation-1:0',
      text: 'これは日本語の音声です。',
      durationMs: 2400,
    })
    emitPlaybackEvent('pet:audio-progress', {
      segmentId: 1,
      utteranceId: 'generation-1:0',
      currentTimeMs: 1200,
      durationMs: 2400,
    })
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-1',
      segmentId: 2,
      sequence: 1,
      utteranceId: 'generation-1:0',
      durationMs: 1800,
    })

    expect(store.state.ttsPlaybackText).toBe('これは日本語の音声です。')
    expect(store.state.ttsPlaybackSegmentId).toBe(2)
    expect(store.state.ttsPlaybackPositionMs).toBe(1200)
    expect(store.state.ttsPlaybackDurationMs).toBe(2400)

    emitPlaybackEvent('pet:audio-progress', {
      segmentId: 2,
      utteranceId: 'generation-1:0',
      currentTimeMs: 3000,
      durationMs: 4200,
    })
    expect(store.state.ttsPlaybackPositionMs).toBe(3000)
    expect(store.state.ttsPlaybackDurationMs).toBe(4200)
  })

  it('clears the old playback text when a new generation starts', () => {
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-1',
      segmentId: 1,
      text: '旧世代の音声',
    })
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-2',
      segmentId: 2,
      text: '新世代の音声',
    })

    expect(store.state.ttsPlaybackText).toBe('新世代の音声')
  })

  it('updates the current segment playback position and duration', () => {
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-1',
      segmentId: 7,
      text: '同期対象',
      durationMs: 5000,
    })
    emitPlaybackEvent('pet:audio-progress', {
      segmentId: 7,
      currentTimeMs: 1234.6,
      durationMs: 5100.2,
    })
    emitPlaybackEvent('pet:audio-progress', {
      segmentId: 999,
      currentTimeMs: 9999,
    })

    expect(store.state.ttsPlaybackPositionMs).toBe(1235)
    expect(store.state.ttsPlaybackDurationMs).toBe(5100)
  })

  it('clears playback state when TTS stops', () => {
    emitPlaybackEvent('pet:audio-started', {
      generationId: 'generation-1',
      segmentId: 3,
      text: '再生中の音声',
      durationMs: 3000,
    })
    emitPlaybackEvent('pet:audio-progress', {
      segmentId: 3,
      currentTimeMs: 900,
    })
    emitPlaybackEvent('pet:tts-stop')

    expect(store.state.isSpeaking).toBe(false)
    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.ttsPlaybackText).toBe('')
    expect(store.state.ttsPlaybackSegmentId).toBeNull()
    expect(store.state.ttsPlaybackPositionMs).toBe(0)
    expect(store.state.ttsPlaybackDurationMs).toBeNull()
  })
})

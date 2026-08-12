import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SocketEvents } from '../net/socketClient'
import { useChatStore } from '../stores/chatStore'
import { useWorkspaceStore } from '../stores/workspaceStore'

type SocketHandler = (payload: unknown) => void

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, SocketHandler>(),
  sendAgentChat: vi.fn(),
  sendInterrupt: vi.fn(),
  sendClientTiming: vi.fn(),
  emit: vi.fn(),
  connected: false,
  clipboardWriteText: vi.fn(),
  requestJson: vi.fn(),
  petSetBehaviorState: vi.fn(() => Promise.resolve()),
  petStopLipSync: vi.fn(() => Promise.resolve()),
  publishRuntime: vi.fn(() => Promise.resolve(true)),
  publishInterrupt: vi.fn(() => Promise.resolve(true)),
  interruptionEpoch: 0,
  llmSequences: new Map<string, number>(),
}))

const agentCallEnvelope = (callIndex = -1) => {
  const call = mocks.sendAgentChat.mock.calls.at(callIndex)
  if (!call) throw new Error('Expected an active Agent request')
  return {
    session_id: call[1],
    request_id: call[3],
    interruption_epoch: call[6],
    generation_id: call[7],
    turn_id: call[8],
    version: 1,
  }
}

vi.mock('@/app/runtime/companionRuntime', () => ({
  getCompanionInterruptionEpoch: () => mocks.interruptionEpoch,
  publishCompanionInterrupt: mocks.publishInterrupt,
  publishCompanionRuntimeEvent: mocks.publishRuntime,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('@/api/client', () => ({
  chatClient: {
    getSocketClient: () => ({
      isConnected: () => mocks.connected,
      connected: { value: mocks.connected },
      on: (event: string, handler: SocketHandler) => {
        const envelopeEvents = new Set([
          SocketEvents.ASR_PARTIAL,
          SocketEvents.ASR_FINAL,
          SocketEvents.LLM_DELTA,
          SocketEvents.LLM_FINAL,
          SocketEvents.AGENT_RESULT,
          SocketEvents.PET_CONTROL,
          SocketEvents.TTS_CHUNK,
          SocketEvents.TTS_DONE,
          SocketEvents.ERROR,
        ])
        mocks.handlers.set(event, (payload: unknown) => {
          if (!envelopeEvents.has(event) || !payload || typeof payload !== 'object') {
            handler(payload)
            return
          }
          const record = Object.fromEntries(
            Object.entries(payload as Record<string, unknown>).filter(([, value]) => value !== undefined),
          )
          if (record.__test_unenveloped === true) {
            delete record.__test_unenveloped
            handler(record)
            return
          }
          const sessionId = typeof record.session_id === 'string' ? record.session_id : 'default'
          const call = [...mocks.sendAgentChat.mock.calls]
            .reverse()
            .find((candidate) => candidate[1] === sessionId)
          const envelope = call
            ? {
                session_id: call[1],
                request_id: call[3],
                interruption_epoch: call[6],
                generation_id: call[7],
                turn_id: call[8],
                version: 1,
              }
            : {
                session_id: sessionId,
                request_id: 'voice-request',
                interruption_epoch: 0,
                generation_id: 'voice-generation',
                turn_id: 'voice-turn',
                version: 1,
              }
          if ((event === SocketEvents.LLM_DELTA || event === SocketEvents.LLM_FINAL) && record.sequence === undefined) {
            const requestId = String(record.request_id ?? envelope.request_id)
            const sequence = mocks.llmSequences.get(requestId) ?? 0
            record.sequence = sequence
            mocks.llmSequences.set(requestId, sequence + 1)
          }
          handler({ ...envelope, ...record })
        })
      },
      emit: mocks.emit,
      sendAgentChat: mocks.sendAgentChat,
      sendInterrupt: mocks.sendInterrupt,
      sendClientTiming: mocks.sendClientTiming,
    }),
  },
}))

vi.mock('@/api/clients/http-client', () => ({
  API_ORIGIN: 'http://localhost:8001',
  CONTROL_ORIGIN: 'http://localhost:38945',
  requestJson: mocks.requestJson,
}))

vi.mock('@/utils/petControl', () => ({
  petControl: {
    setBehaviorState: mocks.petSetBehaviorState,
    stopLipSync: mocks.petStopLipSync,
  },
}))

describe('chatStore', () => {
  let activeStore: ReturnType<typeof useChatStore>

  beforeEach(() => {
    mocks.handlers.clear()
    mocks.sendAgentChat.mockReset()
    mocks.sendInterrupt.mockReset()
    mocks.sendClientTiming.mockReset()
    mocks.emit.mockReset()
    mocks.connected = false
    mocks.clipboardWriteText.mockReset()
    mocks.requestJson.mockReset()
    mocks.petSetBehaviorState.mockClear()
    mocks.petStopLipSync.mockClear()
    mocks.publishRuntime.mockClear()
    mocks.publishInterrupt.mockClear()
    mocks.interruptionEpoch = 0
    mocks.llmSequences.clear()
    window.localStorage.clear()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: mocks.clipboardWriteText,
      },
    })
    setActivePinia(createPinia())
    activeStore = useChatStore()
    activeStore.initChatStore()
  })

  afterEach(() => {
    activeStore.$dispose()
  })

  it('preserves action envelope schema and source metadata', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('hello')

    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      version: 1,
      schema_version: 'yuizaki.action-envelope.v1',
      source: 'agent',
      reply: '我在。',
      actions: [
        {
          type: 'pet_control',
          payload: { emotion_id: 'happy' },
          schema_version: 'yuizaki.pet-control.v1',
          source: 'model_validated',
        },
      ],
    })

    expect(store.state.lastAgentEnvelope).toEqual(expect.objectContaining({
      schema_version: 'yuizaki.action-envelope.v1',
      actions: [
        expect.objectContaining({
          schema_version: 'yuizaki.pet-control.v1',
          source: 'model_validated',
        }),
      ],
    }))
  })

  it('attaches agent steps and memory sources to the matching assistant reply', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('use my saved preference')
    const requestId = mocks.sendAgentChat.mock.calls[0][0].request_id

    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
      text: 'done',
      request_id: requestId,
      assistant_message_id: 22,
    })
    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      version: 1,
      request_id: requestId,
      source: 'agent',
      reply: 'done',
      actions: [
        {
          type: 'tool_trace',
          payload: [{ step_id: 'step-1', title: 'Read file', status: 'completed', tool: 'read_file' }],
        },
        {
          type: 'memory_trace',
          payload: [{ id: 'memory-1', text: 'Prefers concise replies', layer: 'profile', source: 'conversation' }],
        },
      ],
    })

    expect(store.state.messages.at(-1)).toMatchObject({
      id: 22,
      role: 'assistant',
      agentSteps: [{ id: 'step-1', title: 'Read file', status: 'completed', tool: 'read_file' }],
      memorySources: [{ id: 'memory-1', text: 'Prefers concise replies', layer: 'profile', source: 'conversation' }],
    })
  })

  it('projects accepted companion jobs into the assistant trace with terminal metadata', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('run a tool')
    const envelope = agentCallEnvelope()

    window.dispatchEvent(new CustomEvent('companion:job', {
      detail: {
        version: 1,
        type: 'AgentJobCreated',
        workspaceId: 'default',
        sessionId: 'default',
        turnId: envelope.turn_id,
        jobId: 'job-1',
        requestId: envelope.request_id,
        revision: 1,
        interruptionEpoch: envelope.interruption_epoch,
        source: 'mcp',
        timestamp: Date.now(),
        status: 'created',
        data: { toolName: 'read_file', title: 'Read file', progress: 0.4 },
      },
    }))
    window.dispatchEvent(new CustomEvent('companion:job', {
      detail: {
        version: 1,
        type: 'AgentJobCompleted',
        workspaceId: 'default',
        sessionId: 'default',
        turnId: envelope.turn_id,
        jobId: 'job-1',
        requestId: envelope.request_id,
        revision: 2,
        interruptionEpoch: envelope.interruption_epoch,
        source: 'mcp',
        timestamp: Date.now() + 1,
        status: 'completed',
        data: { toolName: 'read_file', title: 'Read file', resultSummary: 'ok', durationMs: 42, artifactCount: 1, artifacts: [{ id: 'artifact-1', name: 'output.txt', url: 'file:///tmp/output.txt' }] },
      },
    }))
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: envelope.request_id, assistant_message_id: 30 })

    expect(store.state.messages.at(-1)).toMatchObject({
      agentSteps: [{
        id: 'job-1',
        jobId: 'job-1',
        status: 'completed',
        tool: 'read_file',
        resultSummary: 'ok',
        durationMs: 42,
        artifactCount: 1,
        progress: 0.4,
        artifacts: [{ id: 'artifact-1', name: 'output.txt', url: 'file:///tmp/output.txt' }],
      }],
    })
  })

  it('does not project a companion job from another session or turn', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('current request')
    const envelope = agentCallEnvelope()
    window.dispatchEvent(new CustomEvent('companion:job', {
      detail: {
        version: 1,
        type: 'AgentJobCompleted',
        workspaceId: 'default',
        sessionId: 'other-session',
        turnId: envelope.turn_id,
        jobId: 'foreign-job',
        requestId: envelope.request_id,
        revision: 1,
        interruptionEpoch: envelope.interruption_epoch,
        source: 'mcp',
        timestamp: Date.now(),
        status: 'completed',
      },
    }))
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: envelope.request_id, assistant_message_id: 31 })
    expect(store.state.messages.at(-1)?.agentSteps).toBeUndefined()
  })

  it('updates an already visible assistant reply when a job reaches its terminal state', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('finish the tool')
    const envelope = agentCallEnvelope()
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: envelope.request_id, assistant_message_id: 32 })

    window.dispatchEvent(new CustomEvent('companion:job', {
      detail: {
        version: 1,
        type: 'AgentJobCompleted',
        workspaceId: 'default',
        sessionId: 'default',
        turnId: envelope.turn_id,
        jobId: 'job-late',
        requestId: envelope.request_id,
        revision: 1,
        interruptionEpoch: envelope.interruption_epoch,
        source: 'mcp',
        timestamp: Date.now(),
        status: 'completed',
        data: { toolName: 'write_file', resultSummary: 'saved', durationMs: 18, artifactCount: 1 },
      },
    }))

    expect(store.state.messages.at(-1)).toMatchObject({
      request_id: envelope.request_id,
      agentSteps: [{ jobId: 'job-late', resultSummary: 'saved', durationMs: 18, artifactCount: 1 }],
    })
  })

  it('keeps provenance metadata optional for legacy memory traces', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('legacy memory')
    const requestId = mocks.sendAgentChat.mock.calls[0][3]
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: requestId, assistant_message_id: 33 })
    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      version: 1,
      request_id: requestId,
      actions: [{ type: 'memory_trace', payload: [{ id: 'memory-legacy', text: 'old fact' }] }],
    })
    expect(store.state.messages.at(-1)?.memorySources).toEqual([{ id: 'memory-legacy', text: 'old fact' }])
  })

  it('bounds memory confidence and keeps retrieval trace identity visible', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('use a traced preference')
    const requestId = mocks.sendAgentChat.mock.calls[0][0].request_id
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: requestId, assistant_message_id: 23 })
    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      version: 1,
      request_id: requestId,
      actions: [{
        type: 'memory_trace',
        payload: [{ id: 'memory-2', text: 'Traceable fact', metadata: { confidence: 1.4, trace_id: 'trace-2' } }],
      }],
    })

    expect(store.state.messages.at(-1)?.memorySources).toEqual([{
      id: 'memory-2',
      text: 'Traceable fact',
      confidence: 1,
      traceId: 'trace-2',
    }])
  })

  it('does not let a late agent result mutate the newly selected session', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('session A request')
    const requestId = mocks.sendAgentChat.mock.calls[0][0].request_id

    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
      text: 'session A reply',
      session_id: 'default',
      request_id: requestId,
      assistant_message_id: 22,
    })
    store.setWorkspaceContext('default', 'session-b')
    store.state.messages = [{ id: 31, role: 'user', content: 'session B message' }]

    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      version: 1,
      session_id: 'default',
      request_id: requestId,
      source: 'agent',
      reply: 'session A reply',
      actions: [{
        type: 'tool_trace',
        payload: [{ step_id: 'late-step', title: 'Late step', status: 'completed' }],
      }],
    })

    expect(store.state.messages).toEqual([{ id: 31, role: 'user', content: 'session B message' }])
    expect(store.state.lastAgentEnvelope).toBeNull()
    expect(store.state.agentEnvelopeTimeline).toEqual([])
  })

  it('rejects generation events that omit their identity envelope', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('identified request')

    mocks.handlers.get(SocketEvents.LLM_DELTA)?.({
      __test_unenveloped: true,
      token: 'must be ignored',
    })

    expect(store.state.currentText).toBe('')
    expect(store.state.isGenerating).toBe(true)
  })

  it('rejects an Agent result that omits its identity envelope', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('identified request')

    mocks.handlers.get(SocketEvents.AGENT_RESULT)?.({
      __test_unenveloped: true,
      version: 1,
      source: 'agent',
      reply: 'must be ignored',
      actions: [],
    })

    expect(store.state.lastAgentEnvelope).toBeNull()
    expect(store.state.agentEnvelopeTimeline).toEqual([])
  })

  it('rejects Pet control that omits its identity envelope', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('identified request')
    const controls: unknown[] = []
    const onControl = (event: Event) => controls.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:llm-control', onControl)

    try {
      mocks.handlers.get(SocketEvents.PET_CONTROL)?.({
        __test_unenveloped: true,
        pet_control: { emotion_id: 'happy' },
      })
    } finally {
      window.removeEventListener('pet:llm-control', onControl)
    }

    expect(controls).toEqual([])
  })

  it('rejects TTS playback that omits its identity envelope', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('identified request')
    const playback: unknown[] = []
    const onPlayback = (event: Event) => playback.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-url', onPlayback)

    try {
      mocks.handlers.get(SocketEvents.TTS_DONE)?.({
        __test_unenveloped: true,
        audio_url: '/audio/unenveloped.wav',
      })
    } finally {
      window.removeEventListener('pet:tts-play-url', onPlayback)
    }

    expect(playback).toEqual([])
    expect(store.state.isTTSPlaying).toBe(false)
  })

  it('rejects an owned backend error that omits its identity envelope', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('identified request')

    mocks.handlers.get(SocketEvents.ERROR)?.({
      __test_unenveloped: true,
      code: 'LLM_ERROR',
      message: 'must be ignored',
    })

    expect(store.state.lastError).toBeNull()
    expect(store.state.isGenerating).toBe(true)
  })

  it('keeps a late error from session A from mutating active session B', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setWorkspaceContext('workspace-a', 'session-a')
    store.sendChat('request A')
    const envelopeA = agentCallEnvelope()

    store.setWorkspaceContext('workspace-b', 'session-b')
    store.sendChat('request B')

    mocks.handlers.get(SocketEvents.ERROR)?.({
      ...envelopeA,
      code: 'LLM_ERROR',
      message: 'late failure A',
    })

    expect(store.state.currentSessionId).toBe('session-b')
    expect(store.state.lastError).toBeNull()
    expect(store.state.isGenerating).toBe(true)
    expect(store.isSessionGenerating('session-b')).toBe(true)
  })

  it('publishes pipeline pet control and TTS lifecycle with the originating interruption epoch', async () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('hello')
    const thinking = mocks.publishRuntime.mock.calls.find(([payload]) => payload.activity === 'thinking')?.[0]
    expect(thinking).toMatchObject({ source: 'chat', activity: 'thinking', interruptionEpoch: 0 })

    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: 'done', request_id: thinking.requestId })
    mocks.handlers.get(SocketEvents.PET_CONTROL)?.({ pet_control: { emotion_id: 'calm' } })
    mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({ audio_url: 'file:///tmp/reply.wav' })
    window.dispatchEvent(new CustomEvent('pet:audio-ended'))
    await Promise.resolve()

    expect(mocks.publishRuntime.mock.calls.map(([payload]) => payload.activity).slice(0, 5)).toEqual([
      'thinking', 'idle', 'executing', 'speaking', 'idle',
    ])
    for (const [payload] of mocks.publishRuntime.mock.calls) {
      expect(payload.interruptionEpoch).toBe(0)
    }
  })

  it('does not stack playback listeners when the store is initialized twice', () => {
    activeStore.initChatStore()
    mocks.publishRuntime.mockClear()

    window.dispatchEvent(new CustomEvent('pet:audio-ended'))

    expect(mocks.publishRuntime).toHaveBeenCalledTimes(1)
    expect(mocks.publishRuntime).toHaveBeenCalledWith(expect.objectContaining({ activity: 'idle' }))
  })

  it('keeps one captured realtime identity through playback end and turn completion', async () => {
    mocks.interruptionEpoch = 4
    mocks.requestJson.mockResolvedValue({ status: 'ok' })
    const store = useChatStore()

    store.setRealtimeRecording(true)
    store.setRealtimePlayback(true)
    mocks.interruptionEpoch = 5
    store.setRealtimePlayback(false)
    const identity = store.getCurrentRealtimeIdentity()
    expect(identity).toBeTruthy()
    await store.completeRealtimeTurn({
      turnId: 'turn-1',
      userText: 'hello',
      assistantText: 'hi',
      model: 'realtime',
      workspaceId: 'default',
      sessionId: 'default',
      interruptionEpoch: 4,
      generationId: identity!.generationId,
      requestId: identity!.requestId,
    })

    const lifecycle = mocks.publishRuntime.mock.calls.map(([payload]) => payload)
    expect(lifecycle.map((payload) => payload.activity)).toEqual(['speaking', 'idle', 'idle'])
    expect(new Set(lifecycle.map((payload) => payload.requestId)).size).toBe(1)
    expect(lifecycle.every((payload) => payload.interruptionEpoch === 4)).toBe(true)
  })

  it('should append user message when sendChat is called', () => {
    mocks.connected = true
    const store = useChatStore()
    const initialLength = store.state.messages.length
    store.sendChat('hello world')
    expect(store.state.messages.length).toBe(initialLength + 1)
    expect(store.state.messages.at(-1)?.role).toBe('user')
  })

  it('keeps a dispatched turn bound to the session that started it', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setWorkspaceContext('workspace-a', 'session-a')
    store.sendChat('look at the desktop')
    store.setWorkspaceContext('workspace-b', 'session-b')

    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
    expect(mocks.sendAgentChat.mock.calls[0][1]).toBe('session-a')
    expect(mocks.sendAgentChat.mock.calls[0][4]).toBe('workspace-a')
  })

  it('sends chat synchronously before any backend visual handshake', () => {
    mocks.connected = true
    const store = useChatStore()

    store.sendChat('plain turn')

    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
  })

  it('uses the active workspace model unless the turn overrides it', () => {
    mocks.connected = true
    const workspaceStore = useWorkspaceStore()
    workspaceStore.activeWorkspace.default_model = 'workspace-fast-model'
    const store = useChatStore()

    store.sendChat('workspace default')
    expect(mocks.sendAgentChat.mock.calls.at(-1)?.[5]).toEqual(expect.objectContaining({
      model: 'workspace-fast-model',
    }))

    store.sendChat('turn override', { chatOptions: { model: 'turn-model' } })
    expect(mocks.sendAgentChat.mock.calls.at(-1)?.[5]).toEqual(expect.objectContaining({
      model: 'turn-model',
    }))
  })

  it('persists the selected response mode in agent requests', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setChatOptions({ response_mode: 'instant' })

    store.sendChat('hello')

    expect(mocks.sendAgentChat.mock.calls.at(-1)?.[5]).toMatchObject({
      response_mode: 'instant',
    })
  })

  it('does not create an unsent user message while disconnected', () => {
    const store = useChatStore()
    const initialLength = store.state.messages.length

    store.sendChat('hello world')

    expect(store.state.messages.length).toBe(initialLength)
    expect(mocks.sendAgentChat).not.toHaveBeenCalled()
    expect(store.state.isGenerating).toBe(false)
    expect(store.state.lastError).toContain('实时通道未连接')
  })

  it('passes normalized sentence emotion cues to TTS playback events', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('play reply')
    const ttsDetails: unknown[] = []
    const onTtsPlay = (event: Event) => {
      ttsDetails.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener('pet:tts-play-url', onTtsPlay)

    try {
      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: '第一句。第二句。' })
      mocks.handlers.get(SocketEvents.PET_CONTROL)?.({
        pet_control: {
          sentence_emotions: [
            {
              sentence_index: '1',
              emotion_id: 'happy',
              expression_name: 'smile',
              duration_ms: '900',
            },
          ],
        },
      })
      mocks.handlers.get(SocketEvents.TTS_DONE)?.({ audio_url: 'file:///tmp/reply.wav' })
    } finally {
      window.removeEventListener('pet:tts-play-url', onTtsPlay)
    }

    expect(store.state.isTTSPlaying).toBe(true)
    expect(store.state.isSpeaking).toBe(true)
    expect(ttsDetails).toEqual([
      expect.objectContaining({
        audio_url: 'file:///tmp/reply.wav',
        text: '第一句。第二句。',
        sentenceEmotionCues: [
          {
            sentenceIndex: 1,
            emotionId: 'happy',
            expressionName: 'smile',
            durationMs: 900,
          },
        ],
      }),
    ])
  })

  it('forwards persisted chat options to connected agent requests', () => {
    mocks.connected = true
    const store = useChatStore()
    store.chatOptions.model = 'gpt-test'
    store.chatOptions.reasoning_effort = 'high'
    store.chatOptions.mcp_enabled = false
    store.chatOptions.web_search_enabled = true
    store.chatOptions.tts_enabled = false
    store.setPromptProfile({
      mode: 'work',
      promptEngineering: {
        workPrompt: '自定义工作提示词',
        dailyPrompt: '自定义日常提示词',
      },
      roleCard: {
        enabled: true,
        name: '結崎',
        personality: '严谨',
      },
      worldBook: {
        enabled: true,
        scanDepth: 6,
        maxEntries: 4,
        budgetTokens: 900,
        entries: [{
          id: 'world-1',
          title: '项目',
          keys: ['项目'],
          secondaryKeys: ['实现'],
          content: '项目背景',
          constant: true,
          selective: true,
          caseSensitive: true,
          matchWholeWords: true,
          insertionOrder: 2,
          probability: 80,
        }],
      },
    })

    store.sendChat('hello world')

    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
    expect(mocks.sendAgentChat.mock.calls[0][5]).toMatchObject({
      model: 'gpt-test',
      reasoning_effort: 'high',
      mcp_enabled: false,
      web_search_enabled: true,
      tts_enabled: false,
      prompt_mode: 'work',
      prompt_profile: {
        mode: 'work',
        promptEngineering: expect.objectContaining({ workPrompt: '自定义工作提示词' }),
        roleCard: expect.objectContaining({ name: '結崎', personality: '严谨' }),
        worldBook: expect.objectContaining({
          enabled: true,
          scanDepth: 6,
          maxEntries: 4,
          budgetTokens: 900,
          entries: [
            expect.objectContaining({
              secondaryKeys: ['实现'],
              constant: true,
              selective: true,
              caseSensitive: true,
              matchWholeWords: true,
              insertionOrder: 2,
              probability: 80,
            }),
          ],
        }),
      },
    })
  })

  it('sends ASR final text through the same prompt, TTS, and pet-link request chain', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setWorkspaceContext('workspace-voice', 'session-voice')
    store.chatOptions.pet_link_enabled = true
    store.chatOptions.web_search_enabled = true
    store.chatOptions.tts_enabled = true
    store.setPetControlContext({
      models: [{ id: 'live2d-main', type: 'live2d' }],
      emotions: ['happy'],
      motionGroups: ['TapBody'],
      motionOptions: [{ group: 'TapBody', index: 0 }],
      expressions: ['smile'],
      parameters: [],
      capabilityRevision: 'live2d:live2d-main:rev-1',
      modelType: 'live2d',
      modelId: 'live2d-main',
      actions: { expression: true, viseme: true },
    })
    store.setPromptProfile({
      mode: 'daily',
      promptEngineering: {
        workPrompt: '自定义工作提示词',
        dailyPrompt: '自定义日常提示词',
      },
      roleCard: {
        enabled: true,
        name: '結崎',
      },
      worldBook: {
        enabled: false,
        entries: [],
      },
    })

    const voiceEnvelope = {
      session_id: 'session-voice',
      request_id: 'voice-request-1',
      generation_id: 'voice-generation-1',
      turn_id: 'voice-turn-1',
      interruption_epoch: 4,
      version: 1,
    }
    mocks.handlers.get(SocketEvents.ASR_FINAL)?.({ ...voiceEnvelope, text: '  语音问题  ' })

    expect(store.state.messages).toEqual([
      expect.objectContaining({ role: 'user', content: '语音问题' }),
    ])
    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
    expect(mocks.sendAgentChat.mock.calls[0][0]).toEqual([
      expect.objectContaining({ role: 'user', content: '语音问题' }),
    ])
    expect(mocks.sendAgentChat.mock.calls[0][1]).toBe('session-voice')
    expect(mocks.sendAgentChat.mock.calls[0][2]).toMatchObject({
      emotions: ['happy'],
      expressions: ['smile'],
      capabilityRevision: 'live2d:live2d-main:rev-1',
      modelType: 'live2d',
      modelId: 'live2d-main',
    })
    expect(mocks.sendAgentChat.mock.calls[0][4]).toBe('workspace-voice')
    expect(mocks.sendAgentChat.mock.calls[0][3]).toBe(voiceEnvelope.request_id)
    expect(mocks.sendAgentChat.mock.calls[0][6]).toBe(voiceEnvelope.interruption_epoch)
    expect(mocks.sendAgentChat.mock.calls[0][7]).toBe(voiceEnvelope.generation_id)
    expect(mocks.sendAgentChat.mock.calls[0][8]).toBe(voiceEnvelope.turn_id)
    expect(mocks.sendAgentChat.mock.calls[0][5]).toMatchObject({
      pet_link_enabled: true,
      web_search_enabled: true,
      tts_enabled: true,
      prompt_mode: 'daily',
      prompt_profile: {
        mode: 'daily',
        promptEngineering: {
          workPrompt: '自定义工作提示词',
          dailyPrompt: '自定义日常提示词',
        },
        roleCard: expect.objectContaining({ enabled: true, name: '結崎' }),
        worldBook: expect.objectContaining({ enabled: false }),
      },
    })
  })

  it('persists realtime turns to the session that started them', async () => {
    mocks.requestJson.mockResolvedValue({ status: 'ok' })
    const store = useChatStore()
    store.setWorkspaceContext('workspace-new', 'session-new')

    await store.completeRealtimeTurn({
      turnId: 'turn-old',
      userText: '旧会话问题',
      assistantText: '旧会话回答',
      model: 'realtime-test',
      workspaceId: 'workspace-old',
      sessionId: 'session-old',
      interruptionEpoch: 0,
      generationId: 'generation-old',
      requestId: 'request-old',
    })

    expect(mocks.requestJson).toHaveBeenCalledWith(
      'http://localhost:8001/api/realtime/transcript',
      expect.objectContaining({
        body: expect.stringContaining('"workspace_id":"workspace-old"'),
      }),
    )
    expect(mocks.requestJson.mock.calls[0][1].body).toContain('"session_id":"session-old"')
    expect(store.state.messages).toEqual([])
    expect(store.sessionRuntime['session-old']).toMatchObject({ unread: true, isGenerating: false })
  })

  it('keeps MCP available while migrating old web-search defaults', () => {
    window.localStorage.setItem('yuizaki.chat.options', JSON.stringify({
      model: 'gpt-test',
      max_tokens: 64000,
      mcp_enabled: true,
      web_search_enabled: true,
      pet_link_enabled: true,
    }))
    window.localStorage.removeItem('yuizaki.chat.options.version')
    setActivePinia(createPinia())

    const store = useChatStore()
    store.initChatStore()

    expect(store.chatOptions.model).toBe('gpt-test')
    expect(store.chatOptions.max_tokens).toBe(64000)
    expect(store.chatOptions.mcp_enabled).toBe(true)
    expect(store.chatOptions.web_search_enabled).toBe(false)
    expect(store.chatOptions.tts_enabled).toBe(true)
    expect(store.chatOptions.prompt_mode).toBe('auto')
    expect(window.localStorage.getItem('yuizaki.chat.options.version')).toBe('7')
  })

  it('can disable TTS output for requests and late playback events', () => {
    mocks.connected = true
    const store = useChatStore()
    const ttsDetails: unknown[] = []
    const stopListener = vi.fn()
    const onTtsPlay = (event: Event) => ttsDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-url', onTtsPlay)
    window.addEventListener('pet:tts-stop', stopListener)

    try {
      store.setTtsEnabled(false)
      store.sendChat('hello world')

      expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
      expect(mocks.sendAgentChat.mock.calls[0][5]).toMatchObject({
        tts_enabled: false,
      })

      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: '第一句。' })
      mocks.handlers.get(SocketEvents.TTS_DONE)?.({ audio_url: 'file:///tmp/reply.wav' })
    } finally {
      window.removeEventListener('pet:tts-play-url', onTtsPlay)
      window.removeEventListener('pet:tts-stop', stopListener)
    }

    expect(ttsDetails).toEqual([])
    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.isSpeaking).toBe(false)
    expect(mocks.petStopLipSync).toHaveBeenCalled()
    expect(stopListener).toHaveBeenCalled()
  })

  it('marks pet playback as interrupted when the user interrupts chat', () => {
    mocks.connected = true
    const store = useChatStore()
    const stopDetails: unknown[] = []
    const onStop = (event: Event) => {
      stopDetails.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener('pet:tts-stop', onStop)

    try {
      store.state.isGenerating = true
      store.state.isSpeaking = true
      store.state.isTTSPlaying = true
      store.state.currentText = 'partial reply'

      store.interrupt()
    } finally {
      window.removeEventListener('pet:tts-stop', onStop)
    }

    expect(mocks.sendInterrupt).toHaveBeenCalledWith(
      store.state.currentSessionId,
      expect.stringMatching(/^interrupt_req_/),
      'manual',
    )
    expect(store.state.isGenerating).toBe(false)
    expect(store.state.isSpeaking).toBe(false)
    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.currentText).toBe('')
    expect(mocks.petStopLipSync).toHaveBeenCalledWith({ interrupted: true })
    expect(mocks.petSetBehaviorState).not.toHaveBeenCalledWith('idle')
    expect(stopDetails).toEqual([{ interrupted: true, petLipSyncHandled: true }])
  })

  it('does not interrupt active speech for the initial VAD candidate', () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.isGenerating = true
    store.state.isSpeaking = true
    store.state.isTTSPlaying = true

    mocks.handlers.get(SocketEvents.ASR_VAD_START)?.({
      session_id: store.state.currentSessionId,
      confirmed_ms: 96,
    })

    expect(mocks.sendInterrupt).not.toHaveBeenCalled()
    expect(store.state.isSpeaking).toBe(true)
  })

  it('automatically interrupts active speech after sustained speech confirmation', () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.isGenerating = true
    store.state.isSpeaking = true
    store.state.isTTSPlaying = true
    store.state.currentText = 'partial reply'

    mocks.handlers.get(SocketEvents.ASR_SPEECH_START)?.({
      session_id: store.state.currentSessionId,
      confirmed_ms: 192,
    })

    expect(mocks.sendInterrupt).toHaveBeenCalledWith(
      store.state.currentSessionId,
      expect.stringMatching(/^interrupt_req_/),
      'voice',
    )
    expect(store.state.isGenerating).toBe(false)
    expect(store.state.isSpeaking).toBe(false)
    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.currentText).toBe('')
  })

  it('does not send an interrupt for sustained speech while the pet is idle', () => {
    mocks.connected = true
    const store = useChatStore()

    mocks.handlers.get(SocketEvents.ASR_SPEECH_START)?.({
      session_id: store.state.currentSessionId,
      confirmed_ms: 192,
    })

    expect(mocks.sendInterrupt).not.toHaveBeenCalled()
    expect(mocks.petStopLipSync).not.toHaveBeenCalled()
  })

  it('uses the final transcript as a fallback interruption for very short speech', () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.isGenerating = true
    store.state.isSpeaking = true
    store.state.isTTSPlaying = true

    mocks.handlers.get(SocketEvents.ASR_FINAL)?.({
      session_id: store.state.currentSessionId,
      text: '停',
    })

    expect(mocks.sendInterrupt).toHaveBeenCalledWith(
      store.state.currentSessionId,
      expect.stringMatching(/^interrupt_req_/),
      'voice',
    )
    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
  })

  it('reports real playback start once and measures interrupt acknowledgement', () => {
    mocks.connected = true
    const store = useChatStore()

    window.dispatchEvent(new CustomEvent('pet:audio-started', {
      detail: { generationId: 'generation-1', sequence: 0 },
    }))

    expect(mocks.sendClientTiming).toHaveBeenCalledWith('playback_start', {
      sessionId: store.state.currentSessionId,
      generationId: 'generation-1',
    })
    mocks.sendClientTiming.mockClear()
    window.dispatchEvent(new CustomEvent('pet:audio-started', {
      detail: { generationId: 'generation-1', sequence: 0 },
    }))
    expect(mocks.sendClientTiming).not.toHaveBeenCalled()

    store.interrupt()
    const requestId = mocks.sendInterrupt.mock.calls.at(-1)?.[1]
    mocks.handlers.get(SocketEvents.INTERRUPT_ACK)?.({
      request_id: requestId,
      session_id: store.state.currentSessionId,
      generation_id: 'generation-1',
    })

    expect(mocks.sendClientTiming).toHaveBeenCalledTimes(1)
    expect(mocks.sendClientTiming).toHaveBeenLastCalledWith('interrupt_ack', expect.objectContaining({
      sessionId: store.state.currentSessionId,
      generationId: 'generation-1',
      elapsedMs: expect.any(Number),
    }))
  })

  it('drops TTS audio while interrupt is pending and from the interrupted generation', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('old request')
    const oldEnvelope = agentCallEnvelope()
    const ttsDetails: unknown[] = []
    const onTtsPlay = (event: Event) => ttsDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-url', onTtsPlay)

    try {
      store.interrupt()
      const requestId = mocks.sendInterrupt.mock.calls.at(-1)?.[1]

      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...oldEnvelope,
        audio_url: '/audio/late-before-ack.wav',
        sequence: 0,
      })
      mocks.handlers.get(SocketEvents.INTERRUPT_ACK)?.({
        request_id: requestId,
        session_id: store.state.currentSessionId,
        generation_id: oldEnvelope.generation_id,
      })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...oldEnvelope,
        audio_url: '/audio/late-after-ack.wav',
        sequence: 1,
      })
      store.sendChat('new request')
      const newEnvelope = agentCallEnvelope()
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...newEnvelope,
        audio_url: '/audio/new-generation.wav',
        sequence: 0,
      })
    } finally {
      window.removeEventListener('pet:tts-play-url', onTtsPlay)
    }

    expect(ttsDetails).toEqual([
      expect.objectContaining({
        audio_url: '/audio/new-generation.wav',
        generationId: agentCallEnvelope().generation_id,
      }),
    ])
  })

  it('cleans up a completed TTS request after its session becomes inactive', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setWorkspaceContext('workspace-a', 'session-a')
    store.sendChat('request A')
    const envelopeA = agentCallEnvelope()
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ ...envelopeA, text: 'reply A' })

    store.setWorkspaceContext('workspace-b', 'session-b')
    mocks.handlers.get(SocketEvents.TTS_DONE)?.({
      ...envelopeA,
      audio_url: '/audio/reply-a.wav',
    })

    expect(store.sessionRuntime['session-a']).toMatchObject({
      requestId: null,
      isGenerating: false,
    })
    expect(store.state.currentSessionId).toBe('session-b')
    expect(store.state.isTTSPlaying).toBe(false)
  })

  it('preserves the full generation envelope in Avatar and TTS playback details', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('animate and speak')
    const envelope = agentCallEnvelope()
    const avatarDetails: unknown[] = []
    const ttsDetails: unknown[] = []
    const onAvatar = (event: Event) => avatarDetails.push((event as CustomEvent<unknown>).detail)
    const onTts = (event: Event) => ttsDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:llm-control', onAvatar)
    window.addEventListener('pet:tts-play-url', onTts)

    try {
      mocks.handlers.get(SocketEvents.PET_CONTROL)?.({
        ...envelope,
        pet_control: { emotion_id: 'happy' },
      })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...envelope,
        audio_url: '/audio/reply.wav',
        sequence: 0,
      })
    } finally {
      window.removeEventListener('pet:llm-control', onAvatar)
      window.removeEventListener('pet:tts-play-url', onTts)
    }

    const expectedDetailEnvelope = {
      version: 1,
      sessionId: envelope.session_id,
      generationId: envelope.generation_id,
      turnId: envelope.turn_id,
      requestId: envelope.request_id,
      interruptionEpoch: envelope.interruption_epoch,
    }
    expect(avatarDetails).toEqual([
      expect.objectContaining(expectedDetailEnvelope),
    ])
    expect(ttsDetails).toEqual([
      expect.objectContaining({ ...expectedDetailEnvelope, sequence: 0 }),
    ])
  })

  it('forwards binary PCM TTS chunks to the in-memory player contract', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('pcm reply')
    const generationId = mocks.sendAgentChat.mock.calls[0][7]
    const pcmDetails: unknown[] = []
    const onPcm = (event: Event) => pcmDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-pcm', onPcm)

    try {
      const audio = new Uint8Array(6_400)
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        audio: audio.buffer,
        audio_format: 'pcm_s16le',
        sample_rate: 32_000,
        channels: 1,
        sample_width_bytes: 2,
        session_id: store.state.currentSessionId,
        sequence: 0,
        chunk_index: 0,
        visemes: [
          { viseme: 'ih', offset_ms: 45, weight: 2 },
          { viseme: 'aa', offset_ms: 0, duration_ms: 30 },
          { viseme: 'invalid', offset_ms: 10 },
        ],
        text: '第一句。',
      })
    } finally {
      window.removeEventListener('pet:tts-play-pcm', onPcm)
    }

    expect(pcmDetails).toEqual([expect.objectContaining({
      audio: expect.any(Uint8Array),
      audioFormat: 'pcm_s16le',
      sampleRate: 32_000,
      channels: 1,
      sampleWidthBytes: 2,
      generationId,
      sequence: 0,
      visemeCues: [
        { viseme: 'aa', offsetMs: 0, durationMs: 30 },
        { viseme: 'ih', offsetMs: 45, weight: 1 },
      ],
      text: '第一句。',
    })])
    expect(store.state.isTTSPlaying).toBe(true)
    expect(store.state.isSpeaking).toBe(true)
  })

  it('can disable Live2D/VRM linkage for requests and playback cues', () => {
    mocks.connected = true
    const store = useChatStore()
    const petControls: unknown[] = []
    const ttsDetails: unknown[] = []
    const onPetControl = (event: Event) => petControls.push((event as CustomEvent<unknown>).detail)
    const onTtsPlay = (event: Event) => ttsDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:llm-control', onPetControl)
    window.addEventListener('pet:tts-play-url', onTtsPlay)

    try {
      store.setPetControlContext({
        models: [{ id: 'live2d-main', type: 'live2d' }],
        emotions: ['happy'],
        motionGroups: ['TapBody'],
        motionOptions: [{ group: 'TapBody', index: 0 }],
        expressions: ['smile'],
        parameters: [],
      })
      store.chatOptions.pet_link_enabled = false
      store.sendChat('hello world')

      expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
      expect(mocks.sendAgentChat.mock.calls[0][2]).toBeUndefined()
      expect(mocks.sendAgentChat.mock.calls[0][5]).toMatchObject({
        pet_link_enabled: false,
      })

      mocks.handlers.get(SocketEvents.PET_CONTROL)?.({
        pet_control: {
          emotion_id: 'happy',
          sentence_emotions: [{ sentence_index: 0, emotion_id: 'happy' }],
        },
      })
      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ text: '第一句。' })
      mocks.handlers.get(SocketEvents.TTS_DONE)?.({ audio_url: 'file:///tmp/reply.wav' })
    } finally {
      window.removeEventListener('pet:llm-control', onPetControl)
      window.removeEventListener('pet:tts-play-url', onTtsPlay)
    }

    expect(petControls).toEqual([])
    expect(ttsDetails).toEqual([
      expect.objectContaining({
        audio_url: 'file:///tmp/reply.wav',
        text: '第一句。',
        petLinkEnabled: false,
        version: 1,
        sessionId: store.state.currentSessionId,
        generationId: expect.any(String),
        turnId: expect.any(String),
        requestId: expect.any(String),
        interruptionEpoch: 0,
      }),
    ])
    expect(mocks.petSetBehaviorState).not.toHaveBeenCalled()
  })

  it('keeps visible history while clearing request context', () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.messages.push(
      { role: 'user', content: '旧问题' },
      { role: 'assistant', content: '旧回答' },
    )

    store.clearContext()
    store.sendChat('新问题')

    expect(store.state.messages.map((message) => message.content)).toEqual([
      '旧问题',
      '旧回答',
      '已清理上下文。之后发送的消息只会携带从这里开始的新上下文。',
      '新问题',
    ])
    expect(mocks.sendAgentChat.mock.calls[0][0]).toEqual([
      expect.objectContaining({ role: 'user', content: '新问题' }),
    ])
  })

  it('can start request context from a selected visible message', () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.messages.push(
      { role: 'user', content: '不再携带的问题' },
      { role: 'assistant', content: '不再携带的回答' },
      { role: 'user', content: '从这里开始' },
    )

    store.setContextStartIndex(2)
    store.sendChat('继续')

    expect(store.state.contextStartIndex).toBe(2)
    expect(mocks.sendAgentChat.mock.calls[0][0]).toEqual([
      expect.objectContaining({ role: 'user', content: '从这里开始' }),
      expect.objectContaining({ role: 'user', content: '继续' }),
    ])
  })

  it('clears speaking state when audio playback ends', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('speak')

    mocks.handlers.get(SocketEvents.TTS_DONE)?.({ audio_url: 'file:///tmp/reply.wav' })
    expect(store.state.isTTSPlaying).toBe(true)
    expect(store.state.isSpeaking).toBe(true)

    window.dispatchEvent(new CustomEvent('pet:audio-ended'))

    expect(store.state.isTTSPlaying).toBe(false)
    expect(store.state.isSpeaking).toBe(false)
  })

  it('records backend errors and clears active generation state', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('fail')
    mocks.handlers.get(SocketEvents.LLM_DELTA)?.({ token: '半截回复' })

    mocks.handlers.get(SocketEvents.ERROR)?.({ code: 'LLM_ERROR', message: '模型请求失败' })

    expect(store.state.lastError).toBe('模型请求失败')
    expect(store.state.currentText).toBe('')
    expect(store.state.isGenerating).toBe(false)
  })

  it('builds and copies a readable transcript', async () => {
    const store = useChatStore()
    store.state.messages.push(
      { role: 'user', content: '帮我看一下屏幕' },
      { role: 'assistant', content: '我会先总结重点。' },
    )

    expect(store.transcriptText()).toBe('你：帮我看一下屏幕\n\n結崎：我会先总结重点。')

    await store.copyTranscript()
    expect(mocks.clipboardWriteText).toHaveBeenCalledWith('你：帮我看一下屏幕\n\n結崎：我会先总结重点。')
  })

  it('keeps local advice out of messages until it is explicitly shown', () => {
    const store = useChatStore()

    const item = store.appendLocalAdvice('记得检查桌宠表情映射', 'heartbeat')

    expect(item).toMatchObject({
      content: '记得检查桌宠表情映射',
      source: 'heartbeat',
    })
    expect(store.state.messages).toEqual([])
    expect(store.transcriptText()).toBe('')
    expect(store.state.adviceFeed).toHaveLength(1)

    expect(store.promoteAdviceToMessage(item?.id || '')).toBe(true)

    expect(store.state.adviceFeed).toEqual([])
    expect(store.state.messages).toEqual([
      expect.objectContaining({
        role: 'assistant',
        content: '[建议] 记得检查桌宠表情映射',
      }),
    ])
    expect(store.promoteAdviceToMessage(item?.id || '')).toBe(false)
  })

  it('trims and clears the local advice feed', () => {
    const store = useChatStore()

    for (let index = 0; index < 25; index += 1) {
      store.appendLocalAdvice(`建议 ${index}`, 'behavior')
    }

    expect(store.state.adviceFeed).toHaveLength(20)
    expect(store.state.adviceFeed[0].content).toBe('建议 24')
    expect(store.state.adviceFeed.at(-1)?.content).toBe('建议 5')

    const dismissedId = store.state.adviceFeed[0].id
    store.dismissAdvice(dismissedId)
    expect(store.state.adviceFeed.some((item) => item.id === dismissedId)).toBe(false)

    store.clearAdviceFeed()
    expect(store.state.adviceFeed).toEqual([])
  })

  it('clears volatile chat state without changing connection handlers', () => {
    const store = useChatStore()
    store.state.messages.push({ role: 'assistant', content: '旧回复' })
    store.state.currentText = '生成中'
    store.state.asrPartialText = '识别中'
    store.state.lastAgentEnvelope = { version: 1, request_id: 'r1', source: 'test', reply: 'ok', actions: [] }
    store.state.agentEnvelopeTimeline.push({ received_at: new Date().toISOString(), version: 1, request_id: 'r1', source: 'test', reply: 'ok', actions: [] })

    store.clearLocalMessages()

    expect(store.state.messages).toEqual([])
    expect(store.state.currentText).toBe('')
    expect(store.state.asrPartialText).toBe('')
    expect(store.state.lastError).toBeNull()
    expect(store.state.lastAgentEnvelope).toBeNull()
    expect(store.state.agentEnvelopeTimeline).toEqual([])
    expect(mocks.handlers.has(SocketEvents.LLM_FINAL)).toBe(true)
  })

  it('can prepare a blank session before history is loaded', () => {
    const store = useChatStore()
    store.state.messages.push({ role: 'assistant', content: 'old session reply' })
    store.state.currentText = 'streaming old reply'
    store.state.asrPartialText = 'partial old voice'
    store.state.lastError = 'old error'

    store.clearLocalMessages()
    store.setWorkspaceContext('workspace-2', 'session-3')

    expect(store.state.currentWorkspaceId).toBe('workspace-2')
    expect(store.state.currentSessionId).toBe('session-3')
    expect(store.state.messages).toEqual([])
    expect(store.state.currentText).toBe('')
    expect(store.state.asrPartialText).toBe('')
    expect(store.state.lastError).toBeNull()
  })

  it('keeps background stream output out of the active session', () => {
    mocks.connected = true
    const store = useChatStore()
    store.setWorkspaceContext('workspace-a', 'session-a')
    store.sendChat('run in A')
    const requestId = mocks.sendAgentChat.mock.calls[0][3]

    store.clearLocalMessages()
    store.setWorkspaceContext('workspace-b', 'session-b')
    mocks.handlers.get(SocketEvents.LLM_DELTA)?.({
      token: 'partial A',
      session_id: 'session-a',
      request_id: requestId,
    })

    expect(store.state.currentText).toBe('')
    expect(store.state.messages).toEqual([])
    expect(store.isSessionGenerating('session-a')).toBe(true)
    expect(store.isSessionGenerating('session-b')).toBe(false)

    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
      text: 'finished A',
      session_id: 'session-a',
      request_id: requestId,
    })

    expect(store.state.currentText).toBe('')
    expect(store.state.messages).toEqual([])
    expect(store.isSessionGenerating('session-a')).toBe(false)
    expect(store.unreadSessionIds).toContain('session-a')
  })

  it('clears session-scoped volatile state when loading history', async () => {
    const store = useChatStore()
    store.state.asrPartialText = '旧识别'
    store.state.currentText = '旧生成'
    store.state.lastAgentEnvelope = { version: 1, request_id: 'old', source: 'tool', reply: 'old', actions: [] }
    store.state.agentEnvelopeTimeline.push({ received_at: new Date().toISOString(), version: 1, request_id: 'old', source: 'tool', reply: 'old', actions: [] })
    mocks.requestJson.mockResolvedValue({
      history: [{ id: 42, role: 'assistant', content: '新会话历史', timestamp: '2026-05-03T00:00:00.000Z' }],
    })

    await store.loadHistory('session-2')

    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/history/session-2?limit=50')
    expect(store.state.currentSessionId).toBe('session-2')
    expect(store.state.messages).toEqual([{ id: 42, role: 'assistant', content: '新会话历史', timestamp: '2026-05-03T00:00:00.000Z' }])
    expect(store.state.currentText).toBe('')
    expect(store.state.asrPartialText).toBe('')
    expect(store.state.lastError).toBeNull()
    expect(store.state.lastAgentEnvelope).toBeNull()
    expect(store.state.agentEnvelopeTimeline).toEqual([])
  })

  it('ignores history responses from a session that is no longer active', async () => {
    const store = useChatStore()
    let resolveSessionA: ((value: unknown) => void) | undefined
    let resolveSessionB: ((value: unknown) => void) | undefined
    mocks.requestJson.mockImplementation((url: string) => new Promise((resolve) => {
      if (url.includes('session-a')) resolveSessionA = resolve
      if (url.includes('session-b')) resolveSessionB = resolve
    }))

    store.setWorkspaceContext('workspace-a', 'session-a')
    const sessionARequest = store.loadHistory('session-a', 'workspace-a')
    store.setWorkspaceContext('workspace-b', 'session-b')
    const sessionBRequest = store.loadHistory('session-b', 'workspace-b')

    resolveSessionB?.({ history: [{ role: 'assistant', content: 'history B' }] })
    await sessionBRequest
    resolveSessionA?.({ history: [{ role: 'assistant', content: 'stale history A' }] })
    await sessionARequest

    expect(store.state.currentSessionId).toBe('session-b')
    expect(store.state.messages).toEqual([expect.objectContaining({ content: 'history B' })])
  })

  it('encodes session ids when loading persisted history', async () => {
    const store = useChatStore()
    mocks.requestJson.mockResolvedValue({ history: [] })

    await store.loadHistory('folder/session 2')

    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/history/folder%2Fsession%202?limit=50')
    expect(store.state.currentSessionId).toBe('folder/session 2')
  })

  it('deletes persisted messages through the database API', async () => {
    const store = useChatStore()
    store.state.messages.push(
      { id: 7, role: 'user', content: '要删除的消息' },
      { role: 'assistant', content: '本地消息' },
    )
    mocks.requestJson.mockResolvedValue({ status: 'deleted' })

    await store.deleteMessage(0)

    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/messages/7', { method: 'DELETE' })
    expect(store.state.messages).toEqual([{ role: 'assistant', content: '本地消息' }])
  })

  it('updates persisted messages through the database API', async () => {
    const store = useChatStore()
    store.state.messages.push({ id: 7, role: 'user', content: '旧问题' })
    mocks.requestJson.mockResolvedValue({
      status: 'updated',
      message: { id: 7, role: 'user', content: '新问题', timestamp: '2026-05-03T00:00:00.000Z' },
    })

    await store.updateMessage(0, ' 新问题 ')

    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/messages/7', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: '新问题' }),
    })
    expect(store.state.messages).toEqual([{ id: 7, role: 'user', content: '新问题', timestamp: '2026-05-03T00:00:00.000Z' }])
  })

  it('trims trailing persisted messages before regenerating from a user message', async () => {
    mocks.connected = true
    const store = useChatStore()
    store.state.messages.push(
      { id: 7, role: 'user', content: '重写这里' },
      { id: 8, role: 'assistant', content: '旧回答' },
      { id: 9, role: 'user', content: '后续问题' },
    )
    mocks.requestJson.mockResolvedValue({ status: 'deleted', deleted_count: 2 })

    const persistedRemoved = await store.regenerateFromMessage(0)

    expect(persistedRemoved).toBe(2)
    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/messages/7/after', { method: 'DELETE' })
    expect(store.state.messages).toEqual([{ id: 7, role: 'user', content: '重写这里' }])
    expect(mocks.sendAgentChat).toHaveBeenCalledTimes(1)
    expect(mocks.sendAgentChat.mock.calls[0][0]).toEqual([{ id: 7, role: 'user', content: '重写这里' }])
  })

  it('attaches persisted ids returned by final socket events', () => {
    mocks.connected = true
    const store = useChatStore()

    store.sendChat('hello world')
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
      text: 'reply',
      session_id: 'default',
      user_message_id: 11,
      assistant_message_id: 12,
    })

    expect(store.state.messages).toEqual([
      expect.objectContaining({ id: 11, role: 'user', content: 'hello world' }),
      expect.objectContaining({ id: 12, role: 'assistant', content: 'reply' }),
    ])
  })

  it('applies a replayed final event exactly once', () => {
    mocks.connected = true
    const store = useChatStore()
    store.sendChat('hello once')
    const requestId = mocks.sendAgentChat.mock.calls[0][3]
    const finalPayload = {
      text: 'one reply',
      session_id: 'default',
      request_id: requestId,
      user_message_id: 31,
      assistant_message_id: 32,
    }

    mocks.handlers.get(SocketEvents.LLM_FINAL)?.(finalPayload)
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.(finalPayload)
    mocks.handlers.get(SocketEvents.LLM_DELTA)?.({
      token: 'late token',
      session_id: 'default',
      request_id: requestId,
    })

    expect(store.state.messages.filter((message) => message.id === 32)).toHaveLength(1)
    expect(store.state.currentText).toBe('')
    expect(store.state.isGenerating).toBe(false)
  })

  it('keeps the generation envelope alive until matching TTS completes', () => {
    mocks.connected = true
    const store = useChatStore()
    const played: unknown[] = []
    const onPlay = (event: Event) => played.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-url', onPlay)

    try {
      store.sendChat('speak this')
      const call = mocks.sendAgentChat.mock.calls[0]
      const envelope = {
        session_id: 'default',
        request_id: call[3],
        interruption_epoch: call[6],
        generation_id: call[7],
        turn_id: call[8],
        version: 1,
      }

      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
        ...envelope,
        envelope_version: 1,
        sequence: 0,
        text: 'spoken reply',
      })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...envelope,
        sequence: 0,
        is_final: false,
        audio_url: '/audio/reply.wav',
        text: 'spoken reply',
      })
      mocks.handlers.get(SocketEvents.TTS_DONE)?.({
        ...envelope,
        sequence: 1,
        is_final: true,
        complete: true,
      })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...envelope,
        sequence: 2,
        is_final: false,
        audio_url: '/audio/late.wav',
        text: 'late',
      })
    } finally {
      window.removeEventListener('pet:tts-play-url', onPlay)
    }

    expect(played).toEqual([
      expect.objectContaining({
        audio_url: '/audio/reply.wav',
        generationId: expect.stringMatching(/^gen_/),
      }),
    ])
  })

  it('releases the generation envelope when the backend cannot produce TTS', () => {
    mocks.connected = true
    const store = useChatStore()
    const played: unknown[] = []
    const onPlay = (event: Event) => played.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:tts-play-url', onPlay)

    try {
      store.sendChat('text only')
      const call = mocks.sendAgentChat.mock.calls[0]
      const envelope = {
        session_id: 'default',
        request_id: call[3],
        interruption_epoch: call[6],
        generation_id: call[7],
        turn_id: call[8],
        version: 1,
      }
      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
        ...envelope,
        envelope_version: 1,
        sequence: 0,
        text: 'text reply',
        tts_expected: false,
      })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({
        ...envelope,
        sequence: 0,
        audio_url: '/audio/late.wav',
        text: 'late',
      })
    } finally {
      window.removeEventListener('pet:tts-play-url', onPlay)
    }

    expect(played).toEqual([])
  })

  it('rejects stale generation events and duplicate LLM sequences after interruption', () => {
    mocks.connected = true
    const store = useChatStore()
    const petControls: unknown[] = []
    const played: unknown[] = []
    const onPetControl = (event: Event) => petControls.push((event as CustomEvent<unknown>).detail)
    const onPlay = (event: Event) => played.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:llm-control', onPetControl)
    window.addEventListener('pet:tts-play-url', onPlay)

    try {
      store.sendChat('turn A')
      const first = mocks.sendAgentChat.mock.calls[0]
      const firstEnvelope = {
        session_id: 'default',
        request_id: first[3],
        interruption_epoch: first[6],
        generation_id: first[7],
        turn_id: first[8],
        version: 1,
      }
      store.interrupt()
      const interruptRequestId = mocks.sendInterrupt.mock.calls.at(-1)?.[1]
      mocks.handlers.get(SocketEvents.INTERRUPT_ACK)?.({
        request_id: interruptRequestId,
        session_id: 'default',
        generation_id: firstEnvelope.generation_id,
      })

      mocks.interruptionEpoch = 1
      store.sendChat('turn B')
      const second = mocks.sendAgentChat.mock.calls[1]
      const secondEnvelope = {
        session_id: 'default',
        request_id: second[3],
        interruption_epoch: second[6],
        generation_id: second[7],
        turn_id: second[8],
        version: 1,
      }

      mocks.handlers.get(SocketEvents.LLM_DELTA)?.({ ...firstEnvelope, envelope_version: 1, sequence: 0, token: 'stale' })
      mocks.handlers.get(SocketEvents.LLM_FINAL)?.({ ...firstEnvelope, envelope_version: 1, sequence: 1, text: 'stale reply' })
      mocks.handlers.get(SocketEvents.PET_CONTROL)?.({ ...firstEnvelope, pet_control: { emotion_id: 'angry' } })
      mocks.handlers.get(SocketEvents.TTS_CHUNK)?.({ ...firstEnvelope, sequence: 0, audio_url: '/audio/stale.wav', text: 'stale' })
      mocks.handlers.get(SocketEvents.LLM_DELTA)?.({ ...secondEnvelope, envelope_version: 1, sequence: 0, token: 'fresh' })
      mocks.handlers.get(SocketEvents.LLM_DELTA)?.({ ...secondEnvelope, envelope_version: 1, sequence: 0, token: 'duplicate' })
      mocks.handlers.get(SocketEvents.LLM_DELTA)?.({ ...secondEnvelope, envelope_version: 1, sequence: 1, token: ' reply' })
    } finally {
      window.removeEventListener('pet:llm-control', onPetControl)
      window.removeEventListener('pet:tts-play-url', onPlay)
    }

    expect(store.state.currentText).toBe('fresh reply')
    expect(store.state.messages.some((message) => message.content === 'stale reply')).toBe(false)
    expect(petControls).toEqual([])
    expect(played).toEqual([])
  })

  it('does not persist hidden reasoning returned by final socket events', () => {
    mocks.connected = true
    const store = useChatStore()

    store.sendChat('explain')
    mocks.handlers.get(SocketEvents.LLM_FINAL)?.({
      text: 'final answer',
      session_id: 'default',
      reasoning_content: 'visible model reasoning',
      assistant_message_id: 21,
    })

    expect(store.state.messages).toEqual([
      expect.objectContaining({ role: 'user', content: 'explain' }),
      expect.objectContaining({
        id: 21,
        role: 'assistant',
        content: 'final answer',
      }),
    ])
    expect(store.state.messages.at(-1)).not.toHaveProperty('reasoning')
  })

  it('clears persisted conversation messages through the session API', async () => {
    const store = useChatStore()
    store.state.currentSessionId = 'session-2'
    store.state.messages.push({ id: 7, role: 'assistant', content: '旧消息' })
    mocks.requestJson.mockResolvedValue({ status: 'deleted' })

    const clearedPersisted = await store.clearConversationMessages()

    expect(clearedPersisted).toBe(true)
    expect(mocks.requestJson).toHaveBeenCalledWith('http://localhost:38945/api/sessions/session-2/messages', { method: 'DELETE' })
    expect(store.state.messages).toEqual([])
  })
})

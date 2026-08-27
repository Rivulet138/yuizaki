import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

const schedulerMocks = vi.hoisted(() => ({
  schedule: vi.fn(),
  cancel: vi.fn(),
}))

const petControlMocks = vi.hoisted(() => ({
  getCatalog: vi.fn(() => Promise.resolve({ models: [] })),
  setModelSelection: vi.fn(),
  triggerEmotion: vi.fn(),
  triggerMotion: vi.fn(),
  triggerExpressionMix: vi.fn(),
  triggerExpression: vi.fn(),
  triggerAvatarCommand: vi.fn(),
}))

vi.mock('@/pet-sentence-emotion-scheduler', () => ({
  PetSentenceEmotionScheduler: class {
    schedule = schedulerMocks.schedule
    cancel = schedulerMocks.cancel
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('@/audio/audio-capture', () => ({
  audioCapture: {
    getIsRecording: () => ({ value: false }),
    getStatus: () => ({
      phase: 'idle',
      permission: 'unknown',
      isRecording: false,
      elapsedMs: 0,
      sampleRate: 16000,
      level: 0,
      peak: 0,
      chunksSent: 0,
      bytesSent: 0,
      error: null,
      startedAt: null,
    }),
    start: vi.fn(),
    stop: vi.fn(),
  },
}))

vi.mock('@/utils/petControl', () => ({
  petControl: petControlMocks,
}))

vi.mock('@/api/client', () => ({
  chatClient: {
    getSocketClient: () => ({
      connected: { value: false },
      isConnected: () => false,
      on: vi.fn(),
      emit: vi.fn(),
      sendAgentChat: vi.fn(),
      sendInterrupt: vi.fn(),
    }),
  },
  shortcutClient: {
    on: vi.fn(),
    off: vi.fn(),
  },
}))

describe('useVoiceConversationBridge sentence emotion scheduling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    schedulerMocks.schedule.mockReset()
    schedulerMocks.cancel.mockReset()
    Object.values(petControlMocks).forEach((mock) => mock.mockClear())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('schedules sentence cues on audio start and cancels on audio end or TTS stop', async () => {
    const { useVoiceConversationBridge } = await import('../app/composables/useVoiceConversationBridge')
    const TestHarness = defineComponent({
      setup() {
        useVoiceConversationBridge()
        return () => h('div')
      },
    })

    const wrapper = mount(TestHarness)
    const sentenceEmotionCues = [{ sentenceIndex: 0, emotionId: 'curious' }]

    window.dispatchEvent(
      new CustomEvent('pet:audio-started', {
        detail: {
          audio_url: 'file:///tmp/reply.wav',
          text: '第一句。',
          sentenceEmotionCues,
          durationMs: 1800,
        },
      }),
    )

    expect(schedulerMocks.schedule).toHaveBeenCalledWith(sentenceEmotionCues, {
      text: '第一句。',
      audioDurationMs: 1800,
    })

    window.dispatchEvent(new CustomEvent('pet:audio-ended'))
    window.dispatchEvent(new CustomEvent('pet:tts-stop'))
    expect(schedulerMocks.cancel).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    expect(schedulerMocks.cancel).toHaveBeenCalledTimes(3)

    window.dispatchEvent(
      new CustomEvent('pet:audio-started', {
        detail: { sentenceEmotionCues: [{ emotionId: 'happy' }] },
      }),
    )
    expect(schedulerMocks.schedule).toHaveBeenCalledTimes(1)
  }, 30000)

  it('uses an attached avatar command even when the legacy payload has no model type', async () => {
    const { useVoiceConversationBridge } = await import('../app/composables/useVoiceConversationBridge')
    const TestHarness = defineComponent({
      setup() {
        useVoiceConversationBridge()
        return () => h('div')
      },
    })
    const wrapper = mount(TestHarness)
    const command = {
      version: 1,
      id: 'python-command',
      streamId: 'python:test',
      sequence: 4,
      issuedAt: Date.now(),
      priority: 50,
      interrupt: 'replace',
      actions: [{ type: 'affect', emotion: 'happy' }],
    }

    window.dispatchEvent(new CustomEvent('pet:llm-control', {
      detail: {
        emotion_id: 'happy',
        expression_mix: [{ expression: 'smile', weight: 1 }],
        avatar_command: command,
      },
    }))
    await vi.waitFor(() => expect(petControlMocks.triggerAvatarCommand).toHaveBeenCalledWith(
      command,
      { source: 'automation' },
    ))
    expect(petControlMocks.triggerEmotion).not.toHaveBeenCalled()
    expect(petControlMocks.triggerExpressionMix).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('normalizes legacy LLM embodiment fields into one avatar command', async () => {
    const { useVoiceConversationBridge } = await import('../app/composables/useVoiceConversationBridge')
    const TestHarness = defineComponent({
      setup() {
        useVoiceConversationBridge()
        return () => h('div')
      },
    })
    const wrapper = mount(TestHarness)

    window.dispatchEvent(new CustomEvent('pet:llm-control', {
      detail: {
        emotion_id: 'curious',
        motion_group: 'Wave',
        motion_index: 2,
        expression_name: 'smile',
        parameter_overrides: [{ id: 'ParamAngleX', value: 8, weight: 0.5 }],
        intensity: 0.7,
        duration_ms: 900,
      },
    }))

    await vi.waitFor(() => expect(petControlMocks.triggerAvatarCommand).toHaveBeenCalledTimes(1))
    const [command, options] = petControlMocks.triggerAvatarCommand.mock.calls[0]
    expect(options).toEqual({ source: 'automation' })
    expect(command).toEqual(expect.objectContaining({
      version: 1,
      streamId: expect.stringMatching(/^voice:/),
      priority: 50,
      interrupt: 'replace',
      actions: [
        { type: 'affect', emotion: 'curious', intensity: 0.7, decayMs: 900 },
        { type: 'expression', name: 'smile', weight: 0.7, fadeOutMs: 900 },
        {
          type: 'parameterPatch',
          patches: [{ id: 'ParamAngleX', value: 8, weight: 0.5, mode: 'set' }],
          durationMs: 900,
        },
        { type: 'motion', group: 'Wave', index: 2, intensity: 0.7 },
      ],
    }))
    expect(petControlMocks.triggerEmotion).not.toHaveBeenCalled()
    expect(petControlMocks.triggerMotion).not.toHaveBeenCalled()
    expect(petControlMocks.triggerExpressionMix).not.toHaveBeenCalled()
    expect(petControlMocks.triggerExpression).not.toHaveBeenCalled()

    wrapper.unmount()
  })
})

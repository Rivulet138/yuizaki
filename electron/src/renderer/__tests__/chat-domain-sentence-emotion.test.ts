import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

const schedulerMocks = vi.hoisted(() => ({
  schedule: vi.fn(),
  cancel: vi.fn(),
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
  petControl: {
    getCatalog: vi.fn(() => Promise.resolve({ models: [] })),
    setModelSelection: vi.fn(),
    triggerEmotion: vi.fn(),
    triggerMotion: vi.fn(),
    triggerExpressionMix: vi.fn(),
    triggerExpression: vi.fn(),
  },
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
  }, 15000)
})

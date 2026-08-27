import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PetSentenceEmotionCue } from '../../shared/pet-control'

const petControlMocks = vi.hoisted(() => ({
  triggerAvatarCommand: vi.fn(() => Promise.resolve({ status: 'accepted' })),
  triggerEmotion: vi.fn(),
  triggerMotion: vi.fn(),
  triggerExpression: vi.fn(),
  triggerExpressionMix: vi.fn(),
}))

vi.mock('../utils/petControl', () => ({ petControl: petControlMocks }))

import {
  applySentenceEmotionCue,
  normalizeSentenceEmotionCues,
  PetSentenceEmotionScheduler,
  resolveSentenceEmotionCueSchedule,
  splitTextIntoSentences,
} from '../pet-sentence-emotion-scheduler'

describe('pet sentence emotion scheduler', () => {
  afterEach(() => {
    vi.useRealTimers()
    Object.values(petControlMocks).forEach((mock) => mock.mockClear())
  })

  it('normalizes snake_case sentence emotion cues and drops no-op cues', () => {
    const cues = normalizeSentenceEmotionCues([
      {
        sentence_index: '1',
        offset_ms: '900',
        emotion_id: 'happy',
        motion_group: 'TapBody',
        motion_index: '2',
        expression_name: 'smile',
        expression_mix: [{ expression: 'smile', weight: 1.5 }],
        parameter_overrides: [{ id: 'ParamCheek', value: '0.7', weight: '0.4' }],
        intensity: '0.8',
        duration_ms: '1200',
      },
      { sentence_index: 2, text: 'metadata only' },
    ])

    expect(cues).toEqual([
      {
        sentenceIndex: 1,
        offsetMs: 900,
        emotionId: 'happy',
        motionGroup: 'TapBody',
        motionIndex: 2,
        expressionName: 'smile',
        expressionMix: [{ expression: 'smile', weight: 1 }],
        parameterOverrides: [{ id: 'ParamCheek', value: 0.7, weight: 0.4 }],
        intensity: 0.8,
        durationMs: 1200,
      },
    ])
  })

  it('derives fallback offsets from sentence index and audio duration', () => {
    expect(splitTextIntoSentences('第一句。Second sentence! 第三句?')).toHaveLength(3)

    const schedule = resolveSentenceEmotionCueSchedule(
      [
        { sentenceIndex: 2, emotionId: 'surprised' },
        { offsetMs: 500, expressionName: 'smile' },
      ],
      { text: '第一句。Second sentence! 第三句?', audioDurationMs: 9000 },
    )

    expect(schedule.map((item) => item.offsetMs)).toEqual([500, 5200])
  })

  it('applies scheduled cues and cancels stale timers', async () => {
    vi.useFakeTimers()
    const applied: PetSentenceEmotionCue[] = []
    const scheduler = new PetSentenceEmotionScheduler({
      applyCue: (cue) => {
        applied.push(cue)
      },
    })

    scheduler.schedule([
      { offsetMs: 100, emotionId: 'happy' },
      { offsetMs: 200, expressionName: 'smile' },
    ])
    scheduler.schedule([{ offsetMs: 50, emotionId: 'curious' }])

    await vi.advanceTimersByTimeAsync(100)

    expect(applied).toEqual([{ offsetMs: 50, emotionId: 'curious' }])
  })

  it('rejects a stale queued callback even when the timer transport cannot cancel it', () => {
    const callbacks: Array<() => void> = []
    const applied: PetSentenceEmotionCue[] = []
    const scheduler = new PetSentenceEmotionScheduler({
      applyCue: (cue) => applied.push(cue),
      setTimeout: (handler) => {
        callbacks.push(handler)
        return callbacks.length as unknown as ReturnType<typeof setTimeout>
      },
      clearTimeout: () => undefined,
    })

    scheduler.schedule([{ emotionId: 'stale' }])
    scheduler.schedule([{ emotionId: 'current' }])
    callbacks.forEach((callback) => callback())

    expect(applied).toEqual([{ emotionId: 'current' }])
  })

  it('routes automation cues through AvatarCommand instead of legacy direct APIs', async () => {
    await applySentenceEmotionCue({
      emotionId: 'happy',
      motionGroup: 'TapBody',
      motionIndex: 2,
      expressionName: 'smile',
      intensity: 0.7,
      durationMs: 900,
    })

    expect(petControlMocks.triggerAvatarCommand).toHaveBeenCalledOnce()
    const [command, options] = petControlMocks.triggerAvatarCommand.mock.calls[0]
    expect(options).toEqual({ source: 'automation' })
    expect(command.actions).toEqual([
      { type: 'affect', emotion: 'happy', intensity: 0.7, decayMs: 900 },
      { type: 'expression', name: 'smile', weight: 0.7, fadeOutMs: 900 },
      { type: 'motion', group: 'TapBody', index: 2, intensity: 0.7 },
    ])
    expect(petControlMocks.triggerEmotion).not.toHaveBeenCalled()
    expect(petControlMocks.triggerMotion).not.toHaveBeenCalled()
    expect(petControlMocks.triggerExpression).not.toHaveBeenCalled()
    expect(petControlMocks.triggerExpressionMix).not.toHaveBeenCalled()
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PetSentenceEmotionCue } from '../../shared/pet-control'
import {
  normalizeSentenceEmotionCues,
  PetSentenceEmotionScheduler,
  resolveSentenceEmotionCueSchedule,
  splitTextIntoSentences,
} from '../pet-sentence-emotion-scheduler'

describe('pet sentence emotion scheduler', () => {
  afterEach(() => {
    vi.useRealTimers()
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
})

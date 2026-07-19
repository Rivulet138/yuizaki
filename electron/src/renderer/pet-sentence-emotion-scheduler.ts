import type {
  PetExpressionMixItem,
  PetExpressionMixPayload,
  PetParameterOverrideItem,
  PetSentenceEmotionCue,
} from '../shared/pet-control'
import { petControl } from './utils/petControl'

type UnknownRecord = Record<string, unknown>
type SentenceEmotionTimer = ReturnType<typeof setTimeout>

export interface PetTtsPlaybackStartedDetail {
  audio_url?: string
  text?: string
  sentenceEmotionCues?: PetSentenceEmotionCue[]
  durationMs?: number
  petLinkEnabled?: boolean
}

export interface ScheduledSentenceEmotionCue {
  cue: PetSentenceEmotionCue
  offsetMs: number
}

interface SentenceEmotionSchedulerDependencies {
  applyCue?: (cue: PetSentenceEmotionCue) => Promise<void> | void
  setTimeout?: (handler: () => void, timeoutMs: number) => SentenceEmotionTimer
  clearTimeout?: (timer: SentenceEmotionTimer) => void
}

const MAX_SENTENCE_CUES = 8
const FALLBACK_SENTENCE_STEP_MS = 1600
const MIN_AUDIO_SENTENCE_STEP_MS = 700
const MAX_AUDIO_SENTENCE_STEP_MS = 2600
const AUDIO_END_GUARD_MS = 250

const isRecord = (value: unknown): value is UnknownRecord => typeof value === 'object' && value !== null && !Array.isArray(value)

const readString = (record: UnknownRecord, ...keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return undefined
}

const readNumber = (record: UnknownRecord, minimum: number, maximum: number, ...keys: string[]): number | undefined => {
  for (const key of keys) {
    const value = record[key]
    if (value === undefined || value === null || value === '') {
      continue
    }
    const number = Number(value)
    if (Number.isFinite(number)) {
      return Math.max(minimum, Math.min(maximum, number))
    }
  }
  return undefined
}

const readInteger = (record: UnknownRecord, minimum: number, maximum: number, ...keys: string[]): number | undefined => {
  const number = readNumber(record, minimum, maximum, ...keys)
  return number === undefined ? undefined : Math.floor(number)
}

const normalizeExpressionMix = (value: unknown): PetExpressionMixItem[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const expressions: PetExpressionMixItem[] = []
  for (const item of value) {
    if (!isRecord(item)) {
      continue
    }
    const expression = readString(item, 'expression')
    if (!expression) {
      continue
    }
    const normalized: PetExpressionMixItem = { expression }
    const weight = readNumber(item, 0, 1, 'weight')
    if (weight !== undefined) {
      normalized.weight = weight
    }
    expressions.push(normalized)
  }

  return expressions.slice(0, 3)
}

const normalizeParameterOverrides = (value: unknown): PetParameterOverrideItem[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const overrides: PetParameterOverrideItem[] = []
  for (const item of value) {
    if (!isRecord(item)) {
      continue
    }
    const id = readString(item, 'id')
    const parameterValue = readNumber(item, -1000, 1000, 'value')
    if (!id || parameterValue === undefined) {
      continue
    }
    const normalized: PetParameterOverrideItem = { id, value: parameterValue }
    const weight = readNumber(item, 0, 1, 'weight')
    if (weight !== undefined) {
      normalized.weight = weight
    }
    overrides.push(normalized)
  }

  return overrides.slice(0, 8)
}

const hasCueAction = (cue: PetSentenceEmotionCue): boolean => Boolean(
  cue.emotionId ||
    cue.motionGroup ||
    cue.expressionName ||
    cue.expressionMix?.length ||
    cue.parameterOverrides?.length,
)

export const normalizeSentenceEmotionCues = (value: unknown): PetSentenceEmotionCue[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const cues: PetSentenceEmotionCue[] = []
  for (const item of value) {
    if (!isRecord(item)) {
      continue
    }

    const cue: PetSentenceEmotionCue = {}
    const sentenceIndex = readInteger(item, 0, 999, 'sentenceIndex', 'sentence_index')
    const offsetMs = readInteger(item, 0, 600000, 'offsetMs', 'offset_ms')
    const motionIndex = readInteger(item, 0, 999, 'motionIndex', 'motion_index')
    const durationMs = readInteger(item, 100, 10000, 'durationMs', 'duration_ms')
    const intensity = readNumber(item, 0, 1, 'intensity')
    const text = readString(item, 'text')
    const emotionId = readString(item, 'emotionId', 'emotion_id')
    const motionGroup = readString(item, 'motionGroup', 'motion_group')
    const expressionName = readString(item, 'expressionName', 'expression_name')
    const expressionMix = normalizeExpressionMix(item.expressionMix ?? item.expression_mix)
    const parameterOverrides = normalizeParameterOverrides(item.parameterOverrides ?? item.parameter_overrides)

    if (sentenceIndex !== undefined) cue.sentenceIndex = sentenceIndex
    if (offsetMs !== undefined) cue.offsetMs = offsetMs
    if (motionIndex !== undefined) cue.motionIndex = motionIndex
    if (durationMs !== undefined) cue.durationMs = durationMs
    if (intensity !== undefined) cue.intensity = intensity
    if (text) cue.text = text
    if (emotionId) cue.emotionId = emotionId
    if (motionGroup) cue.motionGroup = motionGroup
    if (expressionName) cue.expressionName = expressionName
    if (expressionMix.length > 0) cue.expressionMix = expressionMix
    if (parameterOverrides.length > 0) cue.parameterOverrides = parameterOverrides

    if (hasCueAction(cue)) {
      cues.push(cue)
    }
  }

  return cues.slice(0, MAX_SENTENCE_CUES)
}

export const splitTextIntoSentences = (text = ''): string[] => {
  const matches = text.match(/[^。！？.!?\n]+[。！？.!?]?/gu) ?? []
  return matches.map((sentence) => sentence.trim()).filter(Boolean)
}

const resolveFallbackStep = (sentenceCount: number, audioDurationMs?: number): number => {
  if (audioDurationMs === undefined || !Number.isFinite(audioDurationMs) || audioDurationMs <= 0 || sentenceCount <= 0) {
    return FALLBACK_SENTENCE_STEP_MS
  }
  return Math.max(
    MIN_AUDIO_SENTENCE_STEP_MS,
    Math.min(MAX_AUDIO_SENTENCE_STEP_MS, Math.floor(audioDurationMs / sentenceCount)),
  )
}

export const resolveSentenceEmotionCueSchedule = (
  cues: readonly PetSentenceEmotionCue[],
  options: { text?: string; audioDurationMs?: number } = {},
): ScheduledSentenceEmotionCue[] => {
  if (cues.length === 0) {
    return []
  }

  const sentenceCount = Math.max(splitTextIntoSentences(options.text).length, cues.length, 1)
  const fallbackStepMs = resolveFallbackStep(sentenceCount, options.audioDurationMs)
  const maxOffsetMs = options.audioDurationMs && options.audioDurationMs > AUDIO_END_GUARD_MS
    ? options.audioDurationMs - AUDIO_END_GUARD_MS
    : Number.POSITIVE_INFINITY

  return cues
    .map((cue, order): ScheduledSentenceEmotionCue => {
      const sentenceIndex = cue.sentenceIndex ?? order
      const requestedOffset = cue.offsetMs ?? sentenceIndex * fallbackStepMs
      return {
        cue,
        offsetMs: Math.max(0, Math.min(maxOffsetMs, requestedOffset)),
      }
    })
    .sort((left, right) => left.offsetMs - right.offsetMs)
}

export const buildExpressionMixPayload = (cue: PetSentenceEmotionCue): PetExpressionMixPayload | null => {
  const expressions = cue.expressionMix?.length
    ? cue.expressionMix
    : cue.expressionName
      ? [{ expression: cue.expressionName, weight: cue.intensity ?? 1 }]
      : []

  if (expressions.length === 0 && !cue.parameterOverrides?.length) {
    return null
  }

  const payload: PetExpressionMixPayload = { expressions }
  if (cue.parameterOverrides?.length) {
    payload.parameterOverrides = cue.parameterOverrides
  }
  if (cue.intensity !== undefined) {
    payload.intensity = cue.intensity
  }
  if (cue.durationMs !== undefined) {
    payload.durationMs = cue.durationMs
  }
  return payload
}

export const applySentenceEmotionCue = async (cue: PetSentenceEmotionCue): Promise<void> => {
  if (cue.emotionId) {
    await petControl.triggerEmotion(cue.emotionId, { source: 'automation' })
  }
  if (cue.motionGroup) {
    await petControl.triggerMotion(cue.motionGroup, cue.motionIndex ?? 0, { source: 'automation' })
  }

  const expressionMixPayload = buildExpressionMixPayload(cue)
  if (expressionMixPayload) {
    await petControl.triggerExpressionMix(expressionMixPayload, { source: 'automation' })
  } else if (cue.expressionName) {
    await petControl.triggerExpression(cue.expressionName, { source: 'automation' })
  }
}

export class PetSentenceEmotionScheduler {
  private readonly applyCue: (cue: PetSentenceEmotionCue) => Promise<void> | void
  private readonly scheduleTimeout: (handler: () => void, timeoutMs: number) => SentenceEmotionTimer
  private readonly cancelTimeout: (timer: SentenceEmotionTimer) => void
  private timers: SentenceEmotionTimer[] = []

  constructor(dependencies: SentenceEmotionSchedulerDependencies = {}) {
    this.applyCue = dependencies.applyCue ?? applySentenceEmotionCue
    this.scheduleTimeout = dependencies.setTimeout ?? ((handler, timeoutMs) => setTimeout(handler, timeoutMs))
    this.cancelTimeout = dependencies.clearTimeout ?? ((timer) => clearTimeout(timer))
  }

  schedule(
    cues: readonly PetSentenceEmotionCue[],
    options: { text?: string; audioDurationMs?: number } = {},
  ): ScheduledSentenceEmotionCue[] {
    this.cancel()

    const schedule = resolveSentenceEmotionCueSchedule(cues, options)
    for (const item of schedule) {
      const timer = this.scheduleTimeout(() => {
        void Promise.resolve(this.applyCue(item.cue)).catch((error) => {
          console.debug('[PetSentenceEmotionScheduler] failed to apply sentence cue:', error)
        })
      }, item.offsetMs)
      this.timers.push(timer)
    }
    return schedule
  }

  cancel(): void {
    for (const timer of this.timers) {
      this.cancelTimeout(timer)
    }
    this.timers = []
  }
}

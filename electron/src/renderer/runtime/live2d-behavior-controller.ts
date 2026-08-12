import type * as PIXI from 'pixi.js'
import type { PetCompanionIdleProfile } from '../../shared/pet-control'
import type { Live2DCoreModel } from './live2d-core-model'

export type Live2DBehaviorState =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'reacting'
  | 'sleepy'
  | 'waiting'
  | 'curious'
  | 'focused'
  | 'interrupted'

interface AffectState {
  arousal: number
  focus: number
  valence: number
}

interface BehaviorProfile {
  breathSpeed: number
  breathAmplitude: number
  swayAmplitude: number
  gazeAmplitude: number
  blinkIntervalMs: number
}

interface BehaviorRequest {
  priority: number
  activatedAt: number
  until: number | null
}

interface EmotionCurveProfile {
  riseMs: number
  holdMs: number
  decayMs: number
}

interface EmotionCurve {
  state: Exclude<Live2DBehaviorState, 'idle'>
  impulse: AffectState
  startedAt: number
  riseMs: number
  holdMs: number
  decayMs: number
  endsAt: number
}

export interface Live2DAttentionTarget {
  x: number
  y: number
  strength?: number
  durationMs?: number
}

interface AttentionFocus {
  x: number
  y: number
  strength: number
  updatedAt: number
  holdUntil: number
  fadeUntil: number
}

interface ResolvedAttentionFocus {
  active: boolean
  x: number
  y: number
  strength: number
}

interface ModelParameterCapabilities {
  detected: boolean
  available: string[]
  unavailable: string[]
}

interface IdleBias {
  breathSpeed: number
  breathAmplitude: number
  swayAmplitude: number
  gazeAmplitude: number
  blinkIntervalMs: number
  affect: AffectState
}

const BEHAVIOR_PROFILES: Record<Live2DBehaviorState, BehaviorProfile> = {
  idle: {
    breathSpeed: 0.32,
    breathAmplitude: 0.42,
    swayAmplitude: 0.9,
    gazeAmplitude: 0.42,
    blinkIntervalMs: 4600,
  },
  thinking: {
    breathSpeed: 0.42,
    breathAmplitude: 0.36,
    swayAmplitude: 1.15,
    gazeAmplitude: 0.64,
    blinkIntervalMs: 3300,
  },
  speaking: {
    breathSpeed: 0.38,
    breathAmplitude: 0.32,
    swayAmplitude: 0.72,
    gazeAmplitude: 0.3,
    blinkIntervalMs: 5200,
  },
  reacting: {
    breathSpeed: 0.55,
    breathAmplitude: 0.48,
    swayAmplitude: 1.5,
    gazeAmplitude: 0.72,
    blinkIntervalMs: 2800,
  },
  sleepy: {
    breathSpeed: 0.24,
    breathAmplitude: 0.32,
    swayAmplitude: 0.46,
    gazeAmplitude: 0.22,
    blinkIntervalMs: 2400,
  },
  waiting: {
    breathSpeed: 0.3,
    breathAmplitude: 0.38,
    swayAmplitude: 0.68,
    gazeAmplitude: 0.5,
    blinkIntervalMs: 4200,
  },
  curious: {
    breathSpeed: 0.46,
    breathAmplitude: 0.4,
    swayAmplitude: 1.25,
    gazeAmplitude: 0.85,
    blinkIntervalMs: 3000,
  },
  focused: {
    breathSpeed: 0.34,
    breathAmplitude: 0.28,
    swayAmplitude: 0.55,
    gazeAmplitude: 0.38,
    blinkIntervalMs: 5600,
  },
  interrupted: {
    breathSpeed: 0.58,
    breathAmplitude: 0.36,
    swayAmplitude: 0.95,
    gazeAmplitude: 0.72,
    blinkIntervalMs: 2200,
  },
}

const STATE_PRIORITY: Record<Exclude<Live2DBehaviorState, 'idle'>, number> = {
  sleepy: 4,
  waiting: 6,
  curious: 12,
  focused: 14,
  thinking: 20,
  reacting: 20,
  interrupted: 25,
  speaking: 30,
}

const STATE_AFFECT_IMPULSES: Record<Exclude<Live2DBehaviorState, 'idle'>, AffectState> = {
  sleepy: {
    arousal: -0.22,
    focus: -0.08,
    valence: -0.02,
  },
  waiting: {
    arousal: -0.06,
    focus: 0.18,
    valence: 0.02,
  },
  thinking: {
    arousal: 0.18,
    focus: 0.52,
    valence: -0.04,
  },
  curious: {
    arousal: 0.26,
    focus: 0.44,
    valence: 0.1,
  },
  focused: {
    arousal: 0.08,
    focus: 0.62,
    valence: 0.04,
  },
  speaking: {
    arousal: 0.34,
    focus: 0.22,
    valence: 0.16,
  },
  reacting: {
    arousal: 0.62,
    focus: 0.28,
    valence: 0.22,
  },
  interrupted: {
    arousal: 0.46,
    focus: 0.5,
    valence: -0.12,
  },
}

const STATE_EMOTION_CURVES: Record<Exclude<Live2DBehaviorState, 'idle'>, EmotionCurveProfile> = {
  sleepy: {
    riseMs: 700,
    holdMs: 1800,
    decayMs: 2400,
  },
  waiting: {
    riseMs: 620,
    holdMs: 1400,
    decayMs: 1800,
  },
  thinking: {
    riseMs: 900,
    holdMs: 1200,
    decayMs: 2100,
  },
  curious: {
    riseMs: 420,
    holdMs: 950,
    decayMs: 1400,
  },
  focused: {
    riseMs: 640,
    holdMs: 1800,
    decayMs: 2200,
  },
  speaking: {
    riseMs: 520,
    holdMs: 1200,
    decayMs: 1500,
  },
  reacting: {
    riseMs: 360,
    holdMs: 760,
    decayMs: 1600,
  },
  interrupted: {
    riseMs: 260,
    holdMs: 640,
    decayMs: 1300,
  },
}

const LIVE2D_PARAMETER_IDS = [
  'ParamBreath',
  'ParamBodyAngleY',
  'ParamEyeBallX',
  'ParamEyeBallY',
  'ParamAngleX',
  'ParamAngleY',
  'ParamAngleZ',
  'ParamCheek',
  'ParamBrowLY',
  'ParamBrowRY',
  'ParamBrowLForm',
  'ParamBrowRForm',
  'ParamBrowLAngle',
  'ParamBrowRAngle',
  'ParamMouthForm',
  'ParamEyeLOpen',
  'ParamEyeROpen',
] as const

const DEFAULT_ATTENTION_HOLD_MS = 900
const ATTENTION_FADE_MS = 2400
const ATTENTION_EPSILON = 0.015

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value))

const normalizeBucket = (value?: string | null): string => (value ?? '').trim().toLowerCase()

const normalizeUnit = (value: number | null | undefined, fallback: number): number =>
  clamp(typeof value === 'number' && Number.isFinite(value) ? value : fallback, 0, 1)

const normalizeSignedUnit = (value: number | null | undefined, fallback: number): number =>
  clamp(typeof value === 'number' && Number.isFinite(value) ? value : fallback, -1, 1)

const normalizeFiniteNumber = (value: number | null | undefined, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

const smoothToward = (current: number, target: number, factor: number): number =>
  Math.abs(current - target) < 0.0005 ? target : current + (target - current) * factor

export class Live2DBehaviorController {
  private ticker: ((ticker: PIXI.Ticker) => void) | null = null
  private unavailableParams = new Set<string>()
  private startedAt = performance.now()
  private resolvedState: Live2DBehaviorState = 'idle'
  private activeRequests = new Map<Exclude<Live2DBehaviorState, 'idle'>, BehaviorRequest>()
  private affect: AffectState = {
    arousal: 0,
    focus: 0,
    valence: 0,
  }
  private resolvedAffect: AffectState = {
    arousal: 0,
    focus: 0,
    valence: 0,
  }
  private activeEmotionCurves: EmotionCurve[] = []
  private companionIdleProfile: PetCompanionIdleProfile = {}
  private detectedCoreModel: Live2DCoreModel | null = null
  private availableParams = new Set<string>()
  private nextBlinkAt = 0
  private blinkStartedAt = 0
  private blinkActive = false
  private nextGazeTargetAt = 0
  private gazeX = 0
  private gazeY = 0
  private gazeTargetX = 0
  private gazeTargetY = 0
  private attentionTarget: AttentionFocus | null = null

  constructor(
    private readonly app: PIXI.Application,
    private readonly getCoreModel: () => Live2DCoreModel | null,
  ) {
    this.scheduleNextBlink(performance.now())
    this.scheduleNextGazeTarget(performance.now())
  }

  start(): void {
    if (this.ticker) {
      return
    }

    this.ticker = (ticker) => this.tick(ticker)
    this.app.ticker.add(this.ticker)
  }

  setState(state: Live2DBehaviorState, durationMs = 0): void {
    const now = performance.now()

    if (state === 'idle') {
      this.activeRequests.clear()
      this.activeEmotionCurves = []
      this.resolvedState = 'idle'
      this.resolvedAffect = this.resolveAffect(now)
      this.scheduleNextBlink(now)
      this.scheduleNextGazeTarget(now)
      return
    }

    this.activeRequests.set(state, {
      priority: STATE_PRIORITY[state],
      activatedAt: now,
      until: durationMs > 0 ? now + durationMs : null,
    })
    this.startEmotionCurve(state, now)
    this.resolvedState = this.resolveState(now)
    this.scheduleNextBlink(now)
    this.scheduleNextGazeTarget(now)
  }

  setCompanionIdleProfile(profile: PetCompanionIdleProfile): void {
    this.companionIdleProfile = { ...profile }
    const now = performance.now()
    this.scheduleNextBlink(now)
    this.scheduleNextGazeTarget(now)
  }

  setAttentionTarget(target: Live2DAttentionTarget | null): void {
    if (!target) {
      this.attentionTarget = null
      return
    }

    const strength = normalizeUnit(target.strength, 0.72)
    if (strength <= ATTENTION_EPSILON) {
      this.attentionTarget = null
      return
    }

    const now = performance.now()
    const holdMs = clamp(normalizeFiniteNumber(target.durationMs, DEFAULT_ATTENTION_HOLD_MS), 120, 4000)
    this.attentionTarget = {
      x: normalizeSignedUnit(target.x, 0),
      y: normalizeSignedUnit(target.y, 0),
      strength,
      updatedAt: now,
      holdUntil: now + holdMs,
      fadeUntil: now + holdMs + ATTENTION_FADE_MS,
    }
  }

  getDebugSnapshot(): {
    resolvedState: Live2DBehaviorState
    affect: AffectState
    activeRequests: Array<{ state: Exclude<Live2DBehaviorState, 'idle'>; priority: number; until: number | null }>
    emotionCurves: Array<{ state: Exclude<Live2DBehaviorState, 'idle'>; phase: 'rise' | 'hold' | 'decay'; strength: number; endsInMs: number }>
    companionIdleProfile: PetCompanionIdleProfile
    effectiveProfile: BehaviorProfile
    attention: ResolvedAttentionFocus
    modelCapabilities: ModelParameterCapabilities
  } {
    const now = performance.now()
    const affect = this.resolveAffect(now)
    return {
      resolvedState: this.resolvedState,
      affect,
      emotionCurves: this.activeEmotionCurves.map((curve) => ({
        state: curve.state,
        phase: this.resolveEmotionCurvePhase(curve, now),
        strength: this.resolveEmotionCurveStrength(curve, now),
        endsInMs: Math.max(0, curve.endsAt - now),
      })),
      companionIdleProfile: { ...this.companionIdleProfile },
      effectiveProfile: this.buildEffectiveProfile(this.resolvedState, affect),
      attention: this.resolveAttention(now),
      modelCapabilities: this.getModelCapabilities(),
      activeRequests: [...this.activeRequests.entries()].map(([state, request]) => ({
        state,
        priority: request.priority,
        until: request.until,
      })),
    }
  }

  stop(): void {
    if (this.ticker) {
      this.app.ticker.remove(this.ticker)
      this.ticker = null
    }
    this.unavailableParams.clear()
  }

  private tick(ticker: PIXI.Ticker): void {
    const now = performance.now()
    this.pruneExpiredRequests(now)
    this.pruneEmotionCurves(now)
    this.resolvedState = this.resolveState(now)
    this.decayAffect(ticker.deltaMS)
    this.resolveAttention(now)
    this.resolvedAffect = this.resolveAffect(now)

    const coreModel = this.getCoreModel()
    if (!coreModel) {
      return
    }
    this.detectParameterCapabilities(coreModel)

    const elapsedSeconds = (now - this.startedAt) / 1000
    const profile = this.buildEffectiveProfile(this.resolvedState, this.resolvedAffect)
    this.applyBreath(coreModel, elapsedSeconds, profile)
    this.applyGazeAndSway(coreModel, now, ticker.deltaMS, elapsedSeconds, profile)
    this.applyFacialMicroExpression(coreModel, this.resolvedState, elapsedSeconds)
    this.applyBlink(coreModel, now)
  }

  private pruneExpiredRequests(now: number): void {
    for (const [state, request] of this.activeRequests.entries()) {
      if (request.until !== null && now >= request.until) {
        this.activeRequests.delete(state)
      }
    }
  }

  private resolveState(now: number): Live2DBehaviorState {
    let winner: { state: Exclude<Live2DBehaviorState, 'idle'>; request: BehaviorRequest } | null = null

    for (const [state, request] of this.activeRequests.entries()) {
      if (request.until !== null && now >= request.until) {
        continue
      }
      if (
        !winner ||
        request.priority > winner.request.priority ||
        (request.priority === winner.request.priority && request.activatedAt > winner.request.activatedAt)
      ) {
        winner = { state, request }
      }
    }

    return winner?.state ?? 'idle'
  }

  private startEmotionCurve(state: Exclude<Live2DBehaviorState, 'idle'>, now: number): void {
    const curveProfile = STATE_EMOTION_CURVES[state]
    const impulse = STATE_AFFECT_IMPULSES[state]
    const curve: EmotionCurve = {
      state,
      impulse,
      startedAt: now,
      riseMs: curveProfile.riseMs,
      holdMs: curveProfile.holdMs,
      decayMs: curveProfile.decayMs,
      endsAt: now + curveProfile.riseMs + curveProfile.holdMs + curveProfile.decayMs,
    }
    this.activeEmotionCurves = [
      ...this.activeEmotionCurves.filter((item) => item.state !== state),
      curve,
    ].slice(-4)
  }

  private pruneEmotionCurves(now: number): void {
    this.activeEmotionCurves = this.activeEmotionCurves.filter((curve) => now < curve.endsAt)
  }

  private resolveEmotionCurvePhase(curve: EmotionCurve, now: number): 'rise' | 'hold' | 'decay' {
    const elapsed = now - curve.startedAt
    if (elapsed < curve.riseMs) {
      return 'rise'
    }
    if (elapsed < curve.riseMs + curve.holdMs) {
      return 'hold'
    }
    return 'decay'
  }

  private resolveEmotionCurveStrength(curve: EmotionCurve, now: number): number {
    const elapsed = now - curve.startedAt
    if (elapsed <= 0) {
      return 0
    }
    if (elapsed < curve.riseMs) {
      const progress = clamp(elapsed / Math.max(1, curve.riseMs), 0, 1)
      return progress * progress * (3 - 2 * progress)
    }
    if (elapsed < curve.riseMs + curve.holdMs) {
      return 1
    }
    const decayElapsed = elapsed - curve.riseMs - curve.holdMs
    const progress = clamp(decayElapsed / Math.max(1, curve.decayMs), 0, 1)
    const eased = progress * progress * (3 - 2 * progress)
    return 1 - eased
  }

  private resolveAffect(now: number): AffectState {
    const curveAffect = this.activeEmotionCurves.reduce<AffectState>(
      (acc, curve) => {
        const strength = this.resolveEmotionCurveStrength(curve, now)
        acc.arousal += curve.impulse.arousal * strength
        acc.focus += curve.impulse.focus * strength
        acc.valence += curve.impulse.valence * strength
        return acc
      },
      { arousal: 0, focus: 0, valence: 0 },
    )

    return {
      arousal: clamp(this.affect.arousal + curveAffect.arousal, -1, 1),
      focus: clamp(this.affect.focus + curveAffect.focus, -1, 1),
      valence: clamp(this.affect.valence + curveAffect.valence, -1, 1),
    }
  }

  private decayAffect(deltaMs: number): void {
    const settle = clamp(deltaMs / 1300, 0.01, 0.07)
    this.affect.arousal = smoothToward(this.affect.arousal, 0, settle * 1.35)
    this.affect.focus = smoothToward(this.affect.focus, 0, settle * 0.95)
    this.affect.valence = smoothToward(this.affect.valence, 0, settle * 0.8)
  }

  private buildEffectiveProfile(state: Live2DBehaviorState, affect: AffectState = this.resolvedAffect): BehaviorProfile {
    const base = state === 'idle'
      ? this.applyCompanionIdleBias(BEHAVIOR_PROFILES.idle)
      : BEHAVIOR_PROFILES[state]
    const reducedMotion = state === 'idle' && typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
    if (reducedMotion) {
      return {
        breathSpeed: base.breathSpeed,
        breathAmplitude: 0,
        swayAmplitude: 0,
        gazeAmplitude: 0,
        blinkIntervalMs: 6500,
      }
    }
    const { arousal, focus, valence } = affect
    return {
      breathSpeed: clamp(base.breathSpeed + arousal * 0.22 + focus * 0.06, 0.18, 1.05),
      breathAmplitude: clamp(base.breathAmplitude + arousal * 0.1 - focus * 0.05, 0.18, 0.72),
      swayAmplitude: clamp(base.swayAmplitude + arousal * 0.48 + focus * 0.16, 0.4, 2.4),
      gazeAmplitude: clamp(base.gazeAmplitude + focus * 0.18 - valence * 0.04, 0.15, 0.95),
      blinkIntervalMs: clamp(base.blinkIntervalMs * (1 - arousal * 0.12 - focus * 0.08 + Math.max(0, -valence) * 0.05), 1900, 6500),
    }
  }

  private resolveCompanionIdleBias(): IdleBias {
    const profile = this.companionIdleProfile
    const supportStyle = normalizeBucket(profile.supportStyle)
    const mood = normalizeBucket(profile.mood)
    const stage = normalizeBucket(profile.relationshipStage)
    const trend = normalizeBucket(profile.relationshipTrend)
    const energy = normalizeUnit(profile.energy, 0.72)
    const affinity = normalizeUnit(profile.affinity, 0.5)
    const trust = normalizeUnit(profile.trust, 0.5)
    const intimacy = normalizeUnit(profile.intimacy, affinity)
    const fatigue = normalizeUnit(profile.fatigue, 0)
    const trustShift = clamp(profile.recentTrustShiftCount ?? 0, 0, 4)
    const gratitude = clamp(profile.recentGratitudeCount ?? 0, 0, 4)

    const closeness = (affinity + trust + intimacy) / 3
    const warmth = clamp(closeness * 0.6 + gratitude * 0.08 - trustShift * 0.1, 0, 1)
    const activation = clamp(energy * 0.62 + warmth * 0.24 - fatigue * 0.5, 0, 1)
    const safety = clamp(trust * 0.55 + intimacy * 0.35 - trustShift * 0.12, 0, 1)

    const bias: IdleBias = {
      breathSpeed: (activation - 0.5) * 0.1,
      breathAmplitude: (safety - 0.5) * 0.14 - fatigue * 0.04,
      swayAmplitude: (warmth - 0.5) * 0.42 + activation * 0.2,
      gazeAmplitude: (1 - safety) * 0.14 + (activation - 0.5) * 0.16,
      blinkIntervalMs: (safety - 0.5) * 900 + fatigue * 700 - activation * 320,
      affect: {
        arousal: (activation - 0.5) * 0.18 + trustShift * 0.05,
        focus: supportStyle === 'analytical' ? 0.12 : mood === 'curious' ? 0.14 : 0,
        valence: (warmth - 0.5) * 0.28 + gratitude * 0.05 - trustShift * 0.08,
      },
    }

    if (supportStyle === 'gentle') {
      bias.breathAmplitude += 0.06
      bias.gazeAmplitude -= 0.04
      bias.blinkIntervalMs += 360
      bias.affect.valence += 0.06
    } else if (supportStyle === 'cheerful') {
      bias.breathSpeed += 0.06
      bias.swayAmplitude += 0.28
      bias.blinkIntervalMs -= 280
      bias.affect.arousal += 0.08
      bias.affect.valence += 0.08
    } else if (supportStyle === 'analytical') {
      bias.breathSpeed -= 0.03
      bias.swayAmplitude -= 0.18
      bias.gazeAmplitude += 0.1
      bias.affect.focus += 0.12
    }

    if (mood === 'warm' || mood === 'gentle') {
      bias.breathAmplitude += 0.05
      bias.swayAmplitude += 0.18
      bias.affect.valence += 0.08
    } else if (mood === 'curious') {
      bias.gazeAmplitude += 0.14
      bias.affect.focus += 0.14
    } else if (mood === 'tired') {
      bias.breathSpeed -= 0.07
      bias.swayAmplitude -= 0.24
      bias.blinkIntervalMs -= 420
      bias.affect.arousal -= 0.08
    }

    if (stage === 'close' || stage === 'stable') {
      bias.breathAmplitude += 0.04
      bias.swayAmplitude += 0.12
      bias.affect.valence += 0.04
    } else if (stage === 'warming') {
      bias.gazeAmplitude += 0.06
      bias.affect.focus += 0.04
    }

    if (trend === 'improving' || trend === 'rising') {
      bias.affect.valence += 0.06
      bias.swayAmplitude += 0.12
    } else if (trend === 'steady') {
      bias.breathAmplitude += 0.03
      bias.blinkIntervalMs += 120
      bias.affect.valence += 0.02
    } else if (trend === 'flat') {
      bias.swayAmplitude -= 0.08
      bias.blinkIntervalMs += 160
    } else if (trend === 'strained' || trend === 'declining') {
      bias.gazeAmplitude += 0.1
      bias.blinkIntervalMs -= 260
      bias.affect.valence -= 0.12
    }

    return bias
  }

  private applyCompanionIdleBias(base: BehaviorProfile): BehaviorProfile {
    const bias = this.resolveCompanionIdleBias()
    return {
      breathSpeed: clamp(base.breathSpeed + bias.breathSpeed + bias.affect.arousal * 0.12, 0.18, 1.05),
      breathAmplitude: clamp(base.breathAmplitude + bias.breathAmplitude + bias.affect.valence * 0.08, 0.18, 0.72),
      swayAmplitude: clamp(base.swayAmplitude + bias.swayAmplitude + bias.affect.valence * 0.3, 0.4, 2.4),
      gazeAmplitude: clamp(base.gazeAmplitude + bias.gazeAmplitude + bias.affect.focus * 0.22, 0.15, 0.95),
      blinkIntervalMs: clamp(base.blinkIntervalMs + bias.blinkIntervalMs - bias.affect.arousal * 420, 1900, 6500),
    }
  }

  private applyBreath(coreModel: Live2DCoreModel, elapsedSeconds: number, profile: BehaviorProfile): void {
    const wave = Math.sin(elapsedSeconds * Math.PI * 2 * profile.breathSpeed)
    this.setParameter(coreModel, 'ParamBreath', 0.5 + wave * profile.breathAmplitude * 0.5, 0.45)
    this.setParameter(coreModel, 'ParamBodyAngleY', wave * profile.swayAmplitude * 0.45, 0.18)
  }

  private applyGazeAndSway(
    coreModel: Live2DCoreModel,
    now: number,
    deltaMs: number,
    elapsedSeconds: number,
    profile: BehaviorProfile,
  ): void {
    if (now >= this.nextGazeTargetAt) {
      this.scheduleNextGazeTarget(now)
    }

    const smoothing = clamp(deltaMs / 700, 0.015, 0.08)
    const attention = this.resolveAttention(now)
    const attentionBlend = clamp(attention.strength * (0.72 + Math.max(0, this.resolvedAffect.focus) * 0.18), 0, 0.92)
    const targetX = this.gazeTargetX * (1 - attentionBlend) + attention.x * attentionBlend
    const targetY = this.gazeTargetY * (1 - attentionBlend) + attention.y * attentionBlend
    this.gazeX = smoothToward(this.gazeX, targetX, smoothing)
    this.gazeY = smoothToward(this.gazeY, targetY, smoothing)

    const swayFocus = 1 - attentionBlend * 0.35
    const microSway = Math.sin(elapsedSeconds * 1.17) * profile.swayAmplitude * swayFocus
    this.setParameter(coreModel, 'ParamEyeBallX', this.gazeX * profile.gazeAmplitude, 0.5)
    this.setParameter(coreModel, 'ParamEyeBallY', this.gazeY * profile.gazeAmplitude * 0.55, 0.45)
    this.setParameter(coreModel, 'ParamAngleX', this.gazeX * 5.5 + microSway + attention.x * attentionBlend * 1.8, 0.18)
    this.setParameter(coreModel, 'ParamAngleY', this.gazeY * 3.8 + attention.y * attentionBlend * 1.2, 0.16)
    this.setParameter(coreModel, 'ParamAngleZ', Math.sin(elapsedSeconds * 0.73) * profile.swayAmplitude * 0.55, 0.12)
  }

  private resolveAttention(now: number): ResolvedAttentionFocus {
    const target = this.attentionTarget
    if (!target) {
      return { active: false, x: 0, y: 0, strength: 0 }
    }

    if (now >= target.fadeUntil) {
      this.attentionTarget = null
      return { active: false, x: 0, y: 0, strength: 0 }
    }

    const fadeWindowMs = target.fadeUntil - target.holdUntil
    if (!Number.isFinite(fadeWindowMs) || fadeWindowMs <= 0) {
      this.attentionTarget = null
      return { active: false, x: 0, y: 0, strength: 0 }
    }
    const fade = now <= target.holdUntil ? 1 : 1 - (now - target.holdUntil) / fadeWindowMs
    const strength = clamp(target.strength * fade, 0, 1)
    if (!Number.isFinite(strength) || strength <= ATTENTION_EPSILON) {
      this.attentionTarget = null
      return { active: false, x: 0, y: 0, strength: 0 }
    }

    return {
      active: true,
      x: target.x,
      y: target.y,
      strength,
    }
  }

  private resolveFacialAffect(state: Live2DBehaviorState): AffectState {
    if (state !== 'idle') {
      return { ...this.resolvedAffect }
    }

    const idleAffect = this.resolveCompanionIdleBias().affect
    return {
      arousal: clamp(this.resolvedAffect.arousal + idleAffect.arousal, -1, 1),
      focus: clamp(this.resolvedAffect.focus + idleAffect.focus, -1, 1),
      valence: clamp(this.resolvedAffect.valence + idleAffect.valence, -1, 1),
    }
  }

  private applyFacialMicroExpression(
    coreModel: Live2DCoreModel,
    state: Live2DBehaviorState,
    elapsedSeconds: number,
  ): void {
    const { arousal, focus, valence } = this.resolveFacialAffect(state)
    const microPulse = Math.sin(elapsedSeconds * 1.4) * 0.015
    const cheek = clamp(0.035 + Math.max(0, valence) * 0.32 + Math.max(0, arousal) * 0.08 + microPulse, 0, 0.46)
    const browY = clamp(focus * 0.2 + valence * 0.1 - arousal * 0.04, -0.22, 0.28)
    const browForm = clamp(valence * 0.2 - focus * 0.12, -0.25, 0.25)
    const browAngle = clamp(valence * 4 - focus * 3, -8, 8)

    this.setParameter(coreModel, 'ParamCheek', cheek, 0.1)
    this.setParameter(coreModel, 'ParamBrowLY', browY, 0.08)
    this.setParameter(coreModel, 'ParamBrowRY', browY, 0.08)
    this.setParameter(coreModel, 'ParamBrowLForm', browForm, 0.08)
    this.setParameter(coreModel, 'ParamBrowRForm', browForm, 0.08)
    this.setParameter(coreModel, 'ParamBrowLAngle', browAngle, 0.06)
    this.setParameter(coreModel, 'ParamBrowRAngle', -browAngle, 0.06)

    if (state !== 'speaking') {
      const mouthForm = clamp(valence * 0.34 + arousal * 0.06 - focus * 0.08 + microPulse, -0.32, 0.42)
      this.setParameter(coreModel, 'ParamMouthForm', mouthForm, 0.08)
    }
  }

  private applyBlink(coreModel: Live2DCoreModel, now: number): void {
    if (!this.blinkActive && now >= this.nextBlinkAt) {
      this.blinkActive = true
      this.blinkStartedAt = now
    }

    if (!this.blinkActive) {
      return
    }

    const elapsed = now - this.blinkStartedAt
    const closeMs = 86
    const holdMs = 42
    const openMs = 132
    const totalMs = closeMs + holdMs + openMs

    let eyeOpen: number
    if (elapsed <= closeMs) {
      eyeOpen = 1 - elapsed / closeMs
    } else if (elapsed <= closeMs + holdMs) {
      eyeOpen = 0
    } else if (elapsed <= totalMs) {
      eyeOpen = (elapsed - closeMs - holdMs) / openMs
    } else {
      this.blinkActive = false
      this.scheduleNextBlink(now)
      eyeOpen = 1
    }

    const value = clamp(eyeOpen, 0, 1)
    this.setParameter(coreModel, 'ParamEyeLOpen', value, 1)
    this.setParameter(coreModel, 'ParamEyeROpen', value, 1)
  }

  private scheduleNextBlink(now: number): void {
    const profile = this.buildEffectiveProfile(this.resolvedState, this.resolvedAffect)
    this.nextBlinkAt = now + profile.blinkIntervalMs * (0.55 + Math.random() * 0.9)
  }

  private scheduleNextGazeTarget(now: number): void {
    const profile = this.buildEffectiveProfile(this.resolvedState, this.resolvedAffect)
    this.gazeTargetX = (Math.random() * 2 - 1) * profile.gazeAmplitude
    this.gazeTargetY = (Math.random() * 2 - 1) * profile.gazeAmplitude * 0.55
    this.nextGazeTargetAt = now + 1800 + Math.random() * 3200
  }

  private setParameter(coreModel: Live2DCoreModel, parameterId: string, value: number, weight: number): void {
    this.detectParameterCapabilities(coreModel)
    if (!this.availableParams.has(parameterId) || this.unavailableParams.has(parameterId)) {
      return
    }

    try {
      coreModel.setParameterValueById(parameterId, value, weight)
    } catch (error) {
      this.unavailableParams.add(parameterId)
      console.debug(`[Live2DBehavior] parameter unavailable: ${parameterId}`, error)
    }
  }

  private detectParameterCapabilities(coreModel: Live2DCoreModel): void {
    if (this.detectedCoreModel === coreModel && this.availableParams.size + this.unavailableParams.size > 0) {
      return
    }

    this.detectedCoreModel = coreModel
    this.availableParams.clear()
    this.unavailableParams.clear()

    for (const parameterId of LIVE2D_PARAMETER_IDS) {
      try {
        coreModel.getParameterValueById(parameterId)
        this.availableParams.add(parameterId)
      } catch {
        this.unavailableParams.add(parameterId)
      }
    }
  }

  private getModelCapabilities(): ModelParameterCapabilities {
    return {
      detected: this.availableParams.size + this.unavailableParams.size > 0,
      available: [...this.availableParams].sort(),
      unavailable: [...this.unavailableParams].sort(),
    }
  }
}

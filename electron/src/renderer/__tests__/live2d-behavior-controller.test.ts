import type * as PIXI from 'pixi.js'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Live2DBehaviorController } from '../runtime/live2d-behavior-controller'
import type { Live2DCoreModel } from '../runtime/live2d-core-model'

class FakeTicker {
  private listener: ((ticker: PIXI.Ticker) => void) | null = null

  add(listener: (ticker: PIXI.Ticker) => void): void {
    this.listener = listener
  }

  remove(listener: (ticker: PIXI.Ticker) => void): void {
    if (this.listener === listener) {
      this.listener = null
    }
  }

  step(deltaMs: number): void {
    vi.advanceTimersByTime(deltaMs)
    this.listener?.({ deltaMS: deltaMs } as PIXI.Ticker)
  }
}

class FakeCoreModel implements Live2DCoreModel {
  private values = new Map<string, number>()
  readonly setCalls: Array<{ parameterId: string; value: number }> = []

  constructor(private readonly availableParameters?: Set<string>) {}

  getParameterValueById(parameterId: string): number {
    if (this.availableParameters && !this.availableParameters.has(parameterId)) {
      throw new Error(`Missing parameter: ${parameterId}`)
    }
    return this.values.get(parameterId) ?? 0
  }

  setParameterValueById(parameterId: string, value: number): void {
    if (this.availableParameters && !this.availableParameters.has(parameterId)) {
      throw new Error(`Missing parameter: ${parameterId}`)
    }
    this.setCalls.push({ parameterId, value })
    this.values.set(parameterId, value)
  }
}

const createController = (coreModel = new FakeCoreModel()) => {
  const ticker = new FakeTicker()
  const app = { ticker } as unknown as PIXI.Application
  const controller = new Live2DBehaviorController(app, () => coreModel)
  controller.start()
  return { controller, ticker, coreModel }
}

const runFrames = (ticker: FakeTicker, totalMs: number, frameMs = 100): void => {
  let elapsed = 0
  while (elapsed < totalMs) {
    const stepMs = Math.min(frameMs, totalMs - elapsed)
    ticker.step(stepMs)
    elapsed += stepMs
  }
}

describe('Live2DBehaviorController Phase 2 arbitration', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('restores lower-priority thinking after reacting expires', () => {
    vi.useFakeTimers()
    const { controller, ticker } = createController()

    controller.setState('thinking')
    runFrames(ticker, 120)
    expect(controller.getDebugSnapshot().resolvedState).toBe('thinking')

    controller.setState('reacting', 220)
    runFrames(ticker, 80)
    expect(controller.getDebugSnapshot().resolvedState).toBe('reacting')

    runFrames(ticker, 260)
    expect(controller.getDebugSnapshot().resolvedState).toBe('thinking')
  })

  it('clears active requests when explicitly set back to idle', () => {
    vi.useFakeTimers()
    const { controller, ticker } = createController()

    controller.setState('speaking')
    runFrames(ticker, 100)
    expect(controller.getDebugSnapshot().resolvedState).toBe('speaking')

    controller.setState('idle')
    runFrames(ticker, 50)

    const snapshot = controller.getDebugSnapshot()
    expect(snapshot.resolvedState).toBe('idle')
    expect(snapshot.activeRequests).toHaveLength(0)
  })

  it('arbitrates desktop pet microstates for touch, focus, and interruption feedback', () => {
    vi.useFakeTimers()
    const { controller, ticker } = createController()

    controller.setState('curious', 500)
    runFrames(ticker, 120)
    expect(controller.getDebugSnapshot().resolvedState).toBe('curious')

    controller.setState('focused', 700)
    runFrames(ticker, 120)
    expect(controller.getDebugSnapshot().resolvedState).toBe('focused')

    controller.setState('interrupted', 240)
    runFrames(ticker, 80)
    expect(controller.getDebugSnapshot().resolvedState).toBe('interrupted')

    runFrames(ticker, 300)
    expect(controller.getDebugSnapshot().resolvedState).toBe('focused')
  })

  it('runs affect through a rise, hold, and decay emotion curve', () => {
    vi.useFakeTimers()
    const { controller, ticker } = createController()

    controller.setState('reacting', 160)
    const initial = controller.getDebugSnapshot()
    expect(initial.affect.arousal).toBe(0)
    expect(initial.emotionCurves[0]).toMatchObject({ state: 'reacting', phase: 'rise' })

    runFrames(ticker, 180)
    const midArousal = controller.getDebugSnapshot().affect.arousal
    expect(midArousal).toBeGreaterThan(0.25)
    expect(midArousal).toBeLessThan(0.55)

    runFrames(ticker, 260)
    const held = controller.getDebugSnapshot()
    expect(held.emotionCurves[0].phase).toBe('hold')
    expect(held.affect.arousal).toBeGreaterThan(0.58)

    runFrames(ticker, 3200)
    const settled = controller.getDebugSnapshot()
    expect(settled.emotionCurves).toHaveLength(0)
    expect(settled.affect.arousal).toBeLessThan(0.08)
  })

  it('adjusts idle motion profile from companion relationship state', () => {
    vi.useFakeTimers()
    const { controller } = createController()

    const baseline = controller.getDebugSnapshot().effectiveProfile
    controller.setCompanionIdleProfile({
      supportStyle: 'cheerful',
      mood: 'warm',
      relationshipStage: 'close',
      relationshipTrend: 'rising',
      energy: 0.9,
      affinity: 0.9,
      trust: 0.85,
      intimacy: 0.88,
      recentGratitudeCount: 2,
    })
    const warmProfile = controller.getDebugSnapshot().effectiveProfile

    expect(warmProfile.swayAmplitude).toBeGreaterThan(baseline.swayAmplitude)
    expect(warmProfile.breathSpeed).toBeGreaterThan(baseline.breathSpeed)
    expect(warmProfile.blinkIntervalMs).toBeLessThan(baseline.blinkIntervalMs)

    controller.setCompanionIdleProfile({
      supportStyle: 'analytical',
      mood: 'curious',
      relationshipStage: 'warming',
      relationshipTrend: 'steady',
      energy: 0.6,
      trust: 0.45,
      affinity: 0.45,
    })
    const curiousProfile = controller.getDebugSnapshot().effectiveProfile

    expect(curiousProfile.gazeAmplitude).toBeGreaterThan(baseline.gazeAmplitude)
    expect(curiousProfile.swayAmplitude).toBeLessThan(warmProfile.swayAmplitude)

    controller.setCompanionIdleProfile({
      relationshipTrend: 'steady',
      energy: 0.5,
      trust: 0.5,
      affinity: 0.5,
    })
    const steadyProfile = controller.getDebugSnapshot().effectiveProfile

    expect(steadyProfile.breathAmplitude).toBeGreaterThan(baseline.breathAmplitude)
    expect(steadyProfile.blinkIntervalMs).toBeGreaterThan(baseline.blinkIntervalMs)

    controller.setCompanionIdleProfile({
      relationshipTrend: 'flat',
      energy: 0.5,
      trust: 0.5,
      affinity: 0.5,
    })
    const flatProfile = controller.getDebugSnapshot().effectiveProfile

    expect(flatProfile.blinkIntervalMs).toBeGreaterThan(steadyProfile.blinkIntervalMs)
  })

  it('maps affect into subtle facial micro-expressions', () => {
    vi.useFakeTimers()
    const { controller, ticker, coreModel } = createController()

    controller.setState('reacting', 1200)
    runFrames(ticker, 620)

    expect(coreModel.getParameterValueById('ParamCheek')).toBeGreaterThan(0.12)
    expect(coreModel.getParameterValueById('ParamMouthForm')).toBeGreaterThan(0.08)
    expect(Math.abs(coreModel.getParameterValueById('ParamBrowLY'))).toBeGreaterThan(0.01)
    expect(Math.abs(coreModel.getParameterValueById('ParamBrowLForm'))).toBeGreaterThan(0.01)
  })

  it('does not overwrite mouth form while lip sync owns speaking', () => {
    vi.useFakeTimers()
    const { controller, ticker, coreModel } = createController()
    coreModel.setParameterValueById('ParamMouthForm', 0.7)

    controller.setState('speaking')
    runFrames(ticker, 160)

    expect(coreModel.getParameterValueById('ParamMouthForm')).toBe(0.7)
    expect(coreModel.getParameterValueById('ParamCheek')).toBeGreaterThan(0.05)
  })

  it('detects available model parameters and skips unsupported effects', () => {
    vi.useFakeTimers()
    const availableParameters = new Set([
      'ParamBreath',
      'ParamBodyAngleY',
      'ParamEyeLOpen',
      'ParamEyeROpen',
    ])
    const coreModel = new FakeCoreModel(availableParameters)
    const { controller, ticker } = createController(coreModel)

    controller.setState('reacting', 500)
    runFrames(ticker, 620)

    const snapshot = controller.getDebugSnapshot()
    expect(snapshot.modelCapabilities.detected).toBe(true)
    expect(snapshot.modelCapabilities.available).toContain('ParamBreath')
    expect(snapshot.modelCapabilities.unavailable).toContain('ParamCheek')
    expect(coreModel.setCalls.some((call) => call.parameterId === 'ParamBreath')).toBe(true)
    expect(coreModel.setCalls.some((call) => call.parameterId === 'ParamCheek')).toBe(false)
    expect(coreModel.setCalls.some((call) => call.parameterId === 'ParamAngleX')).toBe(false)
  })

  it('biases eyes and head toward a recent attention target', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { controller, ticker, coreModel } = createController()

    controller.setAttentionTarget({ x: 1, y: 0.5, strength: 1, durationMs: 1000 })
    runFrames(ticker, 1000)

    const snapshot = controller.getDebugSnapshot()
    expect(snapshot.attention.active).toBe(true)
    expect(snapshot.attention.strength).toBeGreaterThan(0.95)
    expect(coreModel.getParameterValueById('ParamEyeBallX')).toBeGreaterThan(0.16)
    expect(coreModel.getParameterValueById('ParamAngleX')).toBeGreaterThan(2.4)
    expect(coreModel.getParameterValueById('ParamEyeBallY')).toBeGreaterThan(0.03)
    expect(coreModel.getParameterValueById('ParamAngleY')).toBeGreaterThan(0.8)
  })

  it('decays attention back toward autonomous gaze', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { controller, ticker, coreModel } = createController()

    controller.setAttentionTarget({ x: -1, y: -0.4, strength: 1, durationMs: 200 })
    runFrames(ticker, 700)
    expect(controller.getDebugSnapshot().attention.active).toBe(true)
    expect(coreModel.getParameterValueById('ParamEyeBallX')).toBeLessThan(-0.08)

    runFrames(ticker, 5200)

    const snapshot = controller.getDebugSnapshot()
    expect(snapshot.attention.active).toBe(false)
    expect(snapshot.attention.strength).toBe(0)
    expect(Math.abs(coreModel.getParameterValueById('ParamEyeBallX'))).toBeLessThan(0.08)
    expect(Math.abs(coreModel.getParameterValueById('ParamEyeBallY'))).toBeLessThan(0.05)
  })

  it('normalizes invalid attention inputs and ignores zero-strength targets', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
    const { controller, ticker, coreModel } = createController()

    controller.setAttentionTarget({
      x: Number.NaN,
      y: Number.POSITIVE_INFINITY,
      strength: 0.8,
      durationMs: Number.NaN,
    })
    runFrames(ticker, 120)
    expect(controller.getDebugSnapshot().attention).toMatchObject({
      active: true,
      x: 0,
      y: 0,
    })

    runFrames(ticker, 6200)
    expect(controller.getDebugSnapshot().attention.active).toBe(false)
    expect(Number.isFinite(coreModel.getParameterValueById('ParamAngleX'))).toBe(true)
    expect(Number.isFinite(coreModel.getParameterValueById('ParamEyeBallX'))).toBe(true)

    controller.setAttentionTarget({ x: 1, y: 1, strength: 0 })
    expect(controller.getDebugSnapshot().attention.active).toBe(false)
  })
})

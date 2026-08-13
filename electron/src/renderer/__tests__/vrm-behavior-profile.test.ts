import { describe, expect, it } from 'vitest'
import { resolveVrmBehaviorProfile } from '../runtime/vrm-runtime-adapter'

describe('VRM behavior profile mapping', () => {
  it('maps high-energy warm relationships into livelier idle motion', () => {
    const baseline = resolveVrmBehaviorProfile('idle')
    const warm = resolveVrmBehaviorProfile('idle', {
      mood: 'warm',
      supportStyle: 'cheerful',
      relationshipTrend: 'rising',
      energy: 0.95,
      affinity: 0.9,
      trust: 0.85,
      intimacy: 0.9,
    })

    expect(warm.gazeAmplitude).toBeGreaterThan(baseline.gazeAmplitude)
    expect(warm.swayAmplitude).toBeGreaterThan(baseline.swayAmplitude)
    expect(warm.breathSpeed).toBeGreaterThan(baseline.breathSpeed)
    expect(warm.expressionWeight).toBeGreaterThan(baseline.expressionWeight)
  })

  it('makes thinking and reacting visibly distinct from listening', () => {
    const listening = resolveVrmBehaviorProfile('listen')
    const thinking = resolveVrmBehaviorProfile('think')
    const reacting = resolveVrmBehaviorProfile('react')

    expect(thinking.gazeAmplitude).toBeGreaterThan(listening.gazeAmplitude)
    expect(reacting.gazeAmplitude).toBeGreaterThan(thinking.gazeAmplitude)
    expect(reacting.expressionWeight).toBeGreaterThan(listening.expressionWeight)
    expect(reacting.motionLoop).toBe(false)
    expect(listening.motionLoop).toBe(true)
  })

  it('keeps profile values bounded when relationship input is invalid or extreme', () => {
    const profile = resolveVrmBehaviorProfile('react', {
      energy: 99,
      affinity: -4,
      trust: Number.NaN,
      intimacy: Number.POSITIVE_INFINITY,
      fatigue: 99,
      relationshipTrend: 'rising',
    })

    expect(profile.gazeAmplitude).toBeGreaterThanOrEqual(0)
    expect(profile.gazeAmplitude).toBeLessThanOrEqual(0.3)
    expect(profile.swayAmplitude).toBeGreaterThanOrEqual(0)
    expect(profile.swayAmplitude).toBeLessThanOrEqual(0.18)
    expect(profile.breathAmplitude).toBeGreaterThanOrEqual(0)
    expect(profile.breathAmplitude).toBeLessThanOrEqual(0.14)
    expect(profile.expressionWeight).toBeGreaterThanOrEqual(0)
    expect(profile.expressionWeight).toBeLessThanOrEqual(1)
  })
})

import { describe, expect, it } from 'vitest'
import {
  resolveCompanionEmbodiment,
  resolveCompanionEmbodimentDelivery,
  type CompanionEmbodimentIntent,
} from '../../shared/companion-embodiment'

const intent = (overrides: Partial<CompanionEmbodimentIntent> = {}): CompanionEmbodimentIntent => ({
  version: 1,
  id: 'embodiment:0:1',
  kind: 'operational',
  state: 'executing',
  source: 'chat',
  confidence: 1,
  issuedAt: 1_000,
  expiresAt: 2_000,
  reducedMotion: false,
  petLinkEnabled: true,
  ...overrides,
})

describe('companion embodiment intent', () => {
  it('maps an unexpired operational intent without carrying persona content', () => {
    const value = intent()
    expect(resolveCompanionEmbodiment(value, 1_250)).toEqual({
      behavior: 'focused',
      durationMs: 750,
      motionAllowed: true,
    })
    expect(value).not.toHaveProperty('persona')
    expect(value).not.toHaveProperty('prompt')
  })

  it('falls back to idle after TTL expiry or when the user disables pet link', () => {
    expect(resolveCompanionEmbodiment(intent(), 2_000)).toEqual({
      behavior: 'idle',
      motionAllowed: false,
      fallbackReason: 'expired',
    })
    expect(resolveCompanionEmbodiment(intent({ petLinkEnabled: false }), 1_250)).toEqual({
      behavior: 'idle',
      motionAllowed: false,
      fallbackReason: 'pet_link_disabled',
    })
  })

  it('suppresses celebratory and error motion under reduced-motion preference', () => {
    expect(resolveCompanionEmbodiment(intent({ state: 'success', reducedMotion: true }), 1_250)).toMatchObject({
      behavior: 'idle',
      motionAllowed: false,
    })
    expect(resolveCompanionEmbodiment(intent({ state: 'error', reducedMotion: true }), 1_250)).toMatchObject({
      behavior: 'waiting',
      motionAllowed: false,
    })
  })

  it('applies the final delivery guard to active states under reduced motion', () => {
    for (const state of ['listening', 'thinking', 'executing', 'speaking'] as const) {
      const resolved = resolveCompanionEmbodimentDelivery(intent({ state, reducedMotion: true }), 1_250)
      expect(resolved.motionAllowed).toBe(false)
      expect(resolved.behavior).toBe(state === 'listening' ? 'waiting' : 'idle')
    }
  })
})

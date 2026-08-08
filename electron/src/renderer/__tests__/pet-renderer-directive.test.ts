import { describe, expect, it } from 'vitest'
import { validatePetControlDirective } from '../../shared/pet-control-validator'
import type { AvatarManifest, PetControlDirective, PetExpressionMixPayload } from '../../shared/pet-control'

const manifest: AvatarManifest = {
  id: 'test-model',
  name: 'Test Model',
  summary: 'test manifest',
  persona: {
    tone: 'neutral',
    traits: [],
    styleRules: [],
  },
  modelJson: './test.model3.json',
  modelTransform: {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  },
  transformDefaults: {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  },
  expressions: [
    {
      id: 'neutral',
      label: 'Neutral',
      kind: 'emotion',
      prompt: 'neutral',
      binding: { mode: 'file', file: 'neutral.exp3.json' },
    },
    {
      id: 'happy',
      label: 'Happy',
      kind: 'emotion',
      prompt: 'happy',
      binding: { mode: 'file', file: 'happy.exp3.json' },
    },
  ],
  parameterControls: [
    {
      id: 'ParamMouthOpenY',
      label: 'Mouth Open',
      prompt: 'open mouth',
      min: 0,
      max: 1,
    },
  ],
  motions: {
    Idle: { group: 'Idle', file: 'idle.motion3.json' },
    IdleSecond: { group: 'Idle', file: 'idle-2.motion3.json' },
  },
}

const normalizeDirective = (directive: PetControlDirective): PetExpressionMixPayload => {
  const validation = validatePetControlDirective(directive, manifest)
  return {
    expressions: validation.directive.expressionMix,
    parameterOverrides: validation.directive.parameterOverrides,
    ...(validation.directive.motion ? { motion: validation.directive.motion } : {}),
    intensity: validation.directive.intensity,
    durationMs: validation.directive.durationMs,
  }
}

describe('pet control directive normalization', () => {
  it('preserves motion, expression mix, and parameter overrides for renderer dispatch', () => {
    const normalized = normalizeDirective({
      expressionMix: [{ expression: 'happy', weight: 1 }],
      parameterOverrides: [{ id: 'ParamMouthOpenY', value: 0.8, weight: 1 }],
      motion: { group: 'Idle', index: 0 },
      intensity: 0.9,
      durationMs: 1200,
    })

    expect(normalized).toEqual({
      expressions: [{ expression: 'happy', weight: 1 }],
      parameterOverrides: [{ id: 'ParamMouthOpenY', value: 0.8, weight: 1 }],
      motion: { group: 'Idle', index: 0 },
      intensity: 0.9,
      durationMs: 1200,
    })
  })

  it('falls back to neutral expression and clamps parameters', () => {
    const normalized = normalizeDirective({
      expressionMix: [{ expression: 'missing', weight: 2 }],
      parameterOverrides: [{ id: 'ParamMouthOpenY', value: 5, weight: 2 }],
      intensity: 2,
      durationMs: 50,
    })

    expect(normalized.expressions).toEqual([{ expression: 'neutral', weight: 1 }])
    expect(normalized.parameterOverrides).toEqual([{ id: 'ParamMouthOpenY', value: 1, weight: 1 }])
    expect(normalized.intensity).toBe(1)
    expect(normalized.durationMs).toBe(100)
  })

  it('rejects a motion index outside the selected group', () => {
    const validation = validatePetControlDirective({
      expressionMix: [],
      parameterOverrides: [],
      motion: { group: 'Idle', index: 2 },
      intensity: 1,
      durationMs: 1000,
    }, manifest)

    expect(validation.valid).toBe(false)
    expect(validation.errors).toContain('Unknown motion target: Idle:2')
  })
})

import { describe, expect, it } from 'vitest'
import {
  resolveAvatarActionFallback,
  type AvatarCapabilitySnapshot,
} from './avatar-command'

const capabilities = (overrides: Partial<AvatarCapabilitySnapshot> = {}): AvatarCapabilitySnapshot => ({
  revision: 'test-revision',
  modelType: 'live2d',
  modelId: 'test-model',
  generatedAt: 0,
  actions: {
    behavior: true,
    affect: true,
    gaze: true,
    motion: true,
    expression: true,
    parameterPatch: true,
    viseme: true,
    cancel: true,
  },
  expressions: ['happy', 'sad'],
  motions: [
    { group: 'Idle', index: 0, label: 'idle' },
    { group: 'TapBody', index: 1, label: 'tap' },
  ],
  parameters: [],
  ...overrides,
})

describe('resolveAvatarActionFallback', () => {
  it('does not substitute an unavailable explicit expression', () => {
    const result = resolveAvatarActionFallback(
      { type: 'expression', name: 'angry', weight: 0.8 },
      capabilities(),
    )

    expect(result).toMatchObject({ action: null, degraded: true })
    expect(result.message).toContain('requested expression was not substituted')
  })

  it('does not substitute an unavailable explicit motion', () => {
    const result = resolveAvatarActionFallback(
      { type: 'motion', group: 'TapBody', index: 9 },
      capabilities(),
    )

    expect(result).toMatchObject({ action: null, degraded: true })
    expect(result.message).toContain('requested motion was not substituted')
  })

  it('resolves a supported semantic motion to its concrete group and index', () => {
    const result = resolveAvatarActionFallback(
      { type: 'motion', semantic: 'tap' },
      capabilities(),
    )

    expect(result).toEqual({
      action: { type: 'motion', semantic: 'tap', group: 'TapBody', index: 1 },
      degraded: false,
    })
  })

  it('suppresses a group motion without an explicit index', () => {
    const result = resolveAvatarActionFallback(
      { type: 'motion', group: 'TapBody' },
      capabilities(),
    )

    expect(result).toMatchObject({ action: null, degraded: true })
    expect(result.message).toContain('requires an explicit index')
  })
})

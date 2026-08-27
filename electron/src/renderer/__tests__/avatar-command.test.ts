import { describe, expect, it } from 'vitest'
import {
  legacyDirectiveToAvatarCommand,
  normalizeAvatarCommand,
  resolveAvatarActionFallback,
  resolveReducedMotionAvatarAction,
  validateAvatarCommandAgainstCapabilities,
  type AvatarCapabilitySnapshot,
} from '../../shared/avatar-command'

const capabilities: AvatarCapabilitySnapshot = {
  revision: 'vrm:model-a:1',
  modelType: 'vrm',
  modelId: 'model-a',
  generatedAt: 1000,
  actions: {
    behavior: true,
    affect: true,
    gaze: true,
    motion: false,
    expression: true,
    parameterPatch: false,
    viseme: true,
    cancel: true,
  },
  expressions: ['happy', 'aa'],
  motions: [],
  parameters: [],
}

describe('AvatarCommand v1', () => {
  it('rejects malformed IPC payloads without throwing', () => {
    expect(normalizeAvatarCommand(null, 1000)).toMatchObject({ ok: false, status: 'rejected' })
    expect(normalizeAvatarCommand({
      version: 1,
      id: 'malformed-affect',
      streamId: 'test-stream',
      sequence: 0,
      issuedAt: 1000,
      priority: 1,
      interrupt: 'replace',
      actions: [{ type: 'affect', emotion: 'celebrate', motion: 'not-a-motion' }],
    }, 1000)).toMatchObject({ ok: false, status: 'rejected' })
  })

  it('normalizes timing, priority and continuous action values', () => {
    const result = normalizeAvatarCommand({
      version: 1,
      id: 'cmd-1',
      streamId: 'test-stream',
      sequence: 2,
      issuedAt: 900,
      expiresAt: 2000,
      priority: 200,
      interrupt: 'replace',
      actions: [
        { type: 'gaze', target: { x: 2, y: -2 }, strength: 3, holdMs: 50000 },
        { type: 'expression', name: 'happy', weight: -1, fadeInMs: -20, fadeOutMs: 99999 },
      ],
    }, 1000)

    expect(result.ok).toBe(true)
    expect(result.command?.priority).toBe(100)
    expect(result.command?.expiresAt).toBe(2000)
    expect(result.command?.actions).toEqual([
      { type: 'gaze', target: { x: 1, y: -1 }, strength: 1, holdMs: 10000 },
      { type: 'expression', name: 'happy', weight: 0, fadeInMs: 0, fadeOutMs: 10000 },
    ])
  })

  it('drops expired commands before execution', () => {
    const result = normalizeAvatarCommand({
      version: 1,
      id: 'stale',
      streamId: 'test-stream',
      sequence: 0,
      issuedAt: 100,
      expiresAt: 999,
      priority: 0,
      interrupt: 'ignore',
      actions: [{ type: 'behavior', behavior: 'idle' }],
    }, 1000)

    expect(result.ok).toBe(false)
    expect(result.status).toBe('dropped')
  })

  it('rejects stale capability revisions and degrades unsupported actions', () => {
    const mismatch = validateAvatarCommandAgainstCapabilities({
      version: 1,
      id: 'cmd-2',
      streamId: 'test-stream',
      sequence: 3,
      capabilityRevision: 'old',
      issuedAt: 1000,
      priority: 10,
      interrupt: 'queue',
      actions: [{ type: 'expression', name: 'happy' }],
    }, capabilities)
    expect(mismatch.status).toBe('rejected')

    const unsupported = validateAvatarCommandAgainstCapabilities({
      version: 1,
      id: 'cmd-3',
      streamId: 'test-stream',
      sequence: 4,
      capabilityRevision: capabilities.revision,
      issuedAt: 1000,
      priority: 10,
      interrupt: 'queue',
      actions: [{ type: 'motion', group: 'Wave', index: 0 }],
    }, capabilities)
    expect(unsupported.status).toBe('degraded')
    expect(unsupported.unsupportedActionIndexes).toEqual([0])
  })

  it('matches named motion capabilities without requiring index zero', () => {
    const result = validateAvatarCommandAgainstCapabilities({
      version: 1,
      id: 'cmd-motion-name',
      streamId: 'test-stream',
      sequence: 5,
      capabilityRevision: capabilities.revision,
      issuedAt: 1000,
      priority: 10,
      interrupt: 'queue',
      actions: [{ type: 'motion', group: 'Wave', intensity: 0.8 }],
    }, {
      ...capabilities,
      actions: { ...capabilities.actions, motion: true },
      motions: [{ group: 'Wave', index: 2, label: 'Wave' }],
    })

    expect(result.status).toBe('accepted')
    expect(result.unsupportedActionIndexes).toEqual([])
  })

  it('falls back to the first available expression or motion for a degraded command', () => {
    const expression = resolveAvatarActionFallback(
      { type: 'expression', name: 'surprised', weight: 0.8 },
      capabilities,
    )
    expect(expression).toMatchObject({
      degraded: true,
      action: { type: 'expression', name: 'happy', weight: 0.8 },
    })
    expect(expression.message).toContain('used \'happy\'')

    const motion = resolveAvatarActionFallback(
      { type: 'motion', group: 'Wave', index: 0 },
      {
        ...capabilities,
        actions: { ...capabilities.actions, motion: true },
        motions: [{ group: 'Idle', index: 0, label: 'Idle' }],
      },
    )
    expect(motion).toMatchObject({
      degraded: true,
      action: { type: 'motion', group: 'Idle', index: 0 },
    })

    const semantic = resolveAvatarActionFallback(
      { type: 'motion', semantic: 'wave' },
      {
        ...capabilities,
        actions: { ...capabilities.actions, motion: true },
        motions: [{ group: 'Wave', index: 2, label: 'Wave' }],
      },
    )
    expect(semantic).toMatchObject({
      degraded: false,
      action: { type: 'motion', group: 'Wave', index: 2 },
    })
  })

  it('does not invent a fallback when the model has no matching capability', () => {
    const result = resolveAvatarActionFallback(
      { type: 'motion', group: 'Wave', index: 0 },
      capabilities,
    )
    expect(result.action).toBeNull()
    expect(result.degraded).toBe(true)
  })

  it('keeps speech cues while softening or suppressing high-motion avatar actions', () => {
    expect(resolveReducedMotionAvatarAction({ type: 'motion', group: 'Wave' })).toMatchObject({
      action: null,
      degraded: true,
    })
    expect(resolveReducedMotionAvatarAction({ type: 'gaze', target: { x: 1, y: 0 } }).action).toBeNull()
    expect(resolveReducedMotionAvatarAction({
      type: 'parameterPatch',
      patches: [{ id: 'ParamAngleX', value: 20 }],
    }).action).toBeNull()
    expect(resolveReducedMotionAvatarAction({ type: 'behavior', behavior: 'react' })).toMatchObject({
      action: { type: 'behavior', behavior: 'listen' },
      degraded: true,
    })
    expect(resolveReducedMotionAvatarAction({ type: 'affect', emotion: 'happy', intensity: 0.9 })).toMatchObject({
      action: { type: 'affect', emotion: 'happy', intensity: 0.35, motion: null },
      degraded: true,
    })
    expect(resolveReducedMotionAvatarAction({ type: 'expression', name: 'happy' })).toMatchObject({
      action: { type: 'expression', name: 'happy', weight: 0.35 },
      degraded: true,
    })
    expect(resolveReducedMotionAvatarAction({ type: 'viseme', viseme: 'aa', weight: 0.8 })).toEqual({
      action: { type: 'viseme', viseme: 'aa', weight: 0.8 },
      degraded: false,
    })
  })

  it('converts legacy pet directives without changing their intent', () => {
    const command = legacyDirectiveToAvatarCommand({
      expressionMix: [{ expression: 'happy', weight: 0.7 }],
      parameterOverrides: [{ id: 'ParamAngleX', value: 12, weight: 0.5 }],
      motion: { group: 'TapBody', index: 2 },
      intensity: 0.8,
      durationMs: 1200,
    }, { id: 'legacy-1', streamId: 'legacy-stream', sequence: 7, issuedAt: 1000 })

    expect(command).toMatchObject({ version: 1, id: 'legacy-1', streamId: 'legacy-stream', sequence: 7 })
    expect(command.actions).toEqual([
      { type: 'expression', name: 'happy', weight: 0.7, fadeOutMs: 1200 },
      {
        type: 'parameterPatch',
        patches: [{ id: 'ParamAngleX', value: 12, weight: 0.5, mode: 'set' }],
        durationMs: 1200,
      },
      { type: 'motion', group: 'TapBody', index: 2, intensity: 0.8 },
    ])
  })
})

import { describe, expect, it, vi } from 'vitest'
import { createProactiveControls } from '../app/composables/useProactiveControls'
import { isProactiveQuietHoursClear } from '../../shared/proactive'

const settings = (overrides: Record<string, unknown> = {}) => ({
  schemaVersion: 'yuizaki.proactive-settings.v1' as const,
  workspaceId: 'default',
  revision: 2,
  updatedAt: 1_787_097_600,
  enabled: true,
  sourceEnabled: { completed_turn_followup: true },
  dnd: false,
  quietHours: { enabled: false, start: '22:00', end: '07:00', timezone: 'Asia/Shanghai' },
  dailyBudget: 3,
  cooldownSeconds: 600,
  retentionDays: 7,
  policyVersion: 'policy-v1',
  ...overrides,
})

const frame = {
  frameId: 'frame-1',
  workspaceId: 'default',
  sessionId: 'session-1',
  sourceKind: 'completed_turn_followup' as const,
  sourceId: 'turn-1',
  sourceEventId: 'event-1',
  sourceCreatedAt: 1_787_097_600,
  createdAt: 1_787_097_601,
  expiresAt: 1_787_184_000,
  projectionVersion: 'projection-v1',
  policyVersion: 'policy-v1',
  authoritative: false as const,
  allowedActions: [] as [],
}

const opportunity = {
  jobId: 'job-1',
  requestId: 'request-1',
  sourceKind: 'completed_turn_followup' as const,
  sourceId: 'turn-1',
  triggerReason: 'completed_turn_followup',
  expiresAt: 1_800_000_000,
  frameId: 'frame-1',
}

const deferred = <T,>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const api = (overrides: Record<string, unknown> = {}) => ({
  settings: vi.fn(async () => settings()),
  updateSettings: vi.fn(async () => settings({ revision: 3 })),
  frames: vi.fn(async () => [frame]),
  deleteFrame: vi.fn(async () => ({ ok: true })),
  rebuildFrames: vi.fn(async () => ({ workspaceId: 'default', projected: 1, tombstoned: 0, projectionVersion: 'projection-v1' })),
  feedback: vi.fn(async () => ({ ok: true })),
  ...overrides,
})

describe('proactive controls', () => {
  it.each([
    ['2026-08-15T13:59:00Z', true],
    ['2026-08-15T14:00:00Z', false],
    ['2026-08-15T21:00:00Z', false],
    ['2026-08-16T00:00:00Z', true],
  ])('enforces cross-midnight quiet hours at %s', async (instant, expected) => {
    const controls = createProactiveControls(api({
      settings: vi.fn(async () => settings({
        quietHours: { enabled: true, start: '22:00', end: '07:00', timezone: 'Asia/Shanghai' },
      })),
    }) as never)
    await controls.load()
    expect(controls.allows('completed_turn_followup', Date.parse(instant))).toBe(expected)
  })

  it('uses IANA timezone DST rules and fails closed for an unknown timezone', () => {
    const dstQuietHours = { enabled: true, start: '02:30', end: '03:30', timezone: 'America/New_York' }
    expect(isProactiveQuietHoursClear(dstQuietHours, Date.parse('2026-03-08T06:59:00Z'))).toBe(true)
    expect(isProactiveQuietHoursClear(dstQuietHours, Date.parse('2026-03-08T07:00:00Z'))).toBe(false)
    expect(isProactiveQuietHoursClear({ ...dstQuietHours, timezone: 'Mars/Olympus' }, Date.now())).toBe(false)
  })

  it('fails closed on backend failure and ignores a late load after invalidation', async () => {
    const late = deferred<ReturnType<typeof settings>>()
    const controls = createProactiveControls(api({ settings: vi.fn(() => late.promise) }) as never)
    const loading = controls.load()
    controls.invalidate()
    late.resolve(settings())
    expect(await loading).toBe(false)
    expect(controls.policyClosed.value).toBe(true)
    expect(controls.allows('completed_turn_followup')).toBe(false)

    const failed = createProactiveControls(api({ settings: vi.fn(async () => { throw new Error('503') }) }) as never)
    expect(await failed.load()).toBe(false)
    expect(failed.settings.value.enabled).toBe(false)
    expect(failed.settings.value.dnd).toBe(true)
  })

  it('keeps updates fail closed and preserves a restrictive opt-out after failure', async () => {
    const controls = createProactiveControls(api({ updateSettings: vi.fn(async () => { throw new Error('timeout') }) }) as never)
    await controls.load()
    expect(await controls.updateSettings({ enabled: false })).toBe(false)
    expect(controls.settings.value.enabled).toBe(false)
    expect(controls.policyClosed.value).toBe(true)
  })

  it('deduplicates double clicks and reuses one feedback id for an idempotent retry', async () => {
    const pending = deferred<{ ok: boolean }>()
    const feedback = vi.fn()
      .mockImplementationOnce(() => pending.promise)
      .mockRejectedValueOnce(new Error('503'))
      .mockResolvedValueOnce({ ok: true })
    const controls = createProactiveControls(api({ feedback }) as never)
    await controls.load()
    const first = controls.submitFeedback(opportunity, 'useful')
    expect(await controls.submitFeedback(opportunity, 'useful')).toBe(false)
    expect(feedback).toHaveBeenCalledTimes(1)
    pending.resolve({ ok: false })
    expect(await first).toBe(false)
    expect(await controls.submitFeedback(opportunity, 'useful')).toBe(false)
    expect(await controls.submitFeedback(opportunity, 'useful')).toBe(true)
    expect(feedback.mock.calls[0]?.[0].feedbackId).toBe(feedback.mock.calls[1]?.[0].feedbackId)
    expect(feedback.mock.calls[1]?.[0].feedbackId).toBe(feedback.mock.calls[2]?.[0].feedbackId)
  })

  it('updates never-source state only after acknowledgement and hides failed deletions', async () => {
    const feedback = vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce({ ok: true })
    const controls = createProactiveControls(api({ feedback, deleteFrame: vi.fn(async () => { throw new Error('denied') }) }) as never)
    await controls.load()
    expect(await controls.submitFeedback(opportunity, 'never_source')).toBe(false)
    expect(controls.settings.value.sourceEnabled.completed_turn_followup).toBe(true)
    expect(await controls.submitFeedback(opportunity, 'never_source')).toBe(true)
    expect(controls.settings.value.sourceEnabled.completed_turn_followup).toBe(false)
    expect(await controls.deleteFrame('frame-1')).toBe(false)
    expect(controls.visibleFrames.value).toEqual([])
    expect(controls.policyClosed.value).toBe(true)
  })

  it('rebuilds activity frames and reloads the authoritative list', async () => {
    const backend = api()
    const controls = createProactiveControls(backend as never)
    expect(await controls.rebuildFrames()).toBe(true)
    expect(backend.rebuildFrames).toHaveBeenCalledWith(1000)
    expect(backend.settings).toHaveBeenCalledOnce()
    expect(backend.frames).toHaveBeenCalledOnce()
    expect(controls.visibleFrames.value).toEqual([frame])
  })
})

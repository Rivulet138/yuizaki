import { afterEach, describe, expect, it, vi } from 'vitest'
import { proactiveClient } from '../api/clients/proactive-client'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { PROACTIVE_SETTINGS_LIMITS, parseProactiveSettings } from '../../shared/proactive'

const settings = {
  schemaVersion: 'yuizaki.proactive-settings.v1',
  workspaceId: 'default',
  revision: 2,
  updatedAt: 1_787_097_600,
  enabled: false,
  sourceEnabled: { completed_turn_followup: true },
  dnd: false,
  quietHours: { enabled: true, start: '22:00', end: '07:00', timezone: 'Asia/Shanghai' },
  dailyBudget: 3,
  cooldownSeconds: 600,
  retentionDays: 7,
  policyVersion: 'policy-v1',
}

describe('proactiveClient', () => {
  it('shares the backend numeric boundaries and rejects values outside them', () => {
    expect(PROACTIVE_SETTINGS_LIMITS).toEqual({
      dailyBudget: { min: 1, max: 20 },
      cooldownSeconds: { min: 0, max: 604800 },
      retentionDays: { min: 1, max: 90 },
    })
    expect(parseProactiveSettings({
      ...settings,
      dailyBudget: 1,
      cooldownSeconds: 604800,
      retentionDays: 90,
    })).not.toBeNull()
    expect(parseProactiveSettings({ ...settings, dailyBudget: 0 })).toBeNull()
    expect(parseProactiveSettings({ ...settings, dailyBudget: 21 })).toBeNull()
    expect(parseProactiveSettings({ ...settings, cooldownSeconds: 604801 })).toBeNull()
    expect(parseProactiveSettings({ ...settings, retentionDays: 91 })).toBeNull()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('uses only the frozen authenticated routes and exact mutation fields', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'proactive-token')
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue(settings) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ...settings, revision: 3, dnd: true }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, duplicate: false }) }))

    await proactiveClient.settings()
    await proactiveClient.updateSettings({ dnd: true }, 2)
    await proactiveClient.feedback({
      feedbackId: 'feedback-1',
      feedback: 'useful',
      jobId: 'job-1',
      requestId: 'request-1',
      sourceKind: 'completed_turn_followup',
      sourceId: 'turn-1',
      triggerReason: 'completed_turn_followup',
      expiresAt: 1_800_000_000,
      frameId: 'frame-1',
    })

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/proactive/settings`, expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/proactive/settings`, expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ expectedRevision: 2, dnd: true }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/api/system/proactive/feedback`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ feedbackId: 'feedback-1', jobId: 'job-1', requestId: 'request-1', sourceKind: 'completed_turn_followup', kind: 'useful' }),
    }))
  })

  it.each([
    null,
    {},
    { ...settings, sourceEnabled: {} },
    { ...settings, schemaVersion: 'unknown' },
  ])('rejects malformed settings fail closed', async (payload) => {
    window.sessionStorage.setItem('yuizaki.control.token', 'proactive-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: vi.fn().mockResolvedValue(payload) }))
    await expect(proactiveClient.settings()).rejects.toThrow('invalid_proactive_settings')
  })

  it('accepts the backend activity-frame envelope and Unix-second timestamps', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'proactive-token')
    const frame = {
      schemaVersion: 'yuizaki.activity-frame.v1',
      frameId: 'frame-1',
      workspaceId: 'default',
      sessionId: 'session-1',
      sourceKind: 'completed_turn_followup',
      sourceId: 'turn-1',
      sourceEventId: 'event-1',
      sourceCreatedAt: 1_787_097_600,
      createdAt: 1_787_097_601,
      expiresAt: 1_787_184_000,
      projectionVersion: 'activity-frame.v1',
      policyVersion: 'proactive-policy.v1',
      authoritative: false,
      allowedActions: [],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        schemaVersion: 'yuizaki.activity-frame.v1',
        workspaceId: 'default',
        frames: [frame],
      }),
    }))

    const { schemaVersion: _schemaVersion, ...expectedFrame } = frame
    await expect(proactiveClient.frames()).resolves.toEqual([expectedFrame])
  })

  it('rebuilds activity frames through the bounded backend endpoint', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'proactive-token')
    const payload = { workspaceId: 'default', projected: 4, tombstoned: 1, projectionVersion: 'activity-frame.v1' }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(proactiveClient.rebuildFrames(500)).resolves.toEqual(payload)
    expect(fetchMock).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/activity-frames/rebuild`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ limit: 500 }) }),
    )
  })
})

import { describe, expect, it, vi } from 'vitest'
import { createFailClosedProactiveSettings, type ActivityFrameSummary, type ProactiveFeedbackSummary, type ProactiveOpportunityIdentity } from '@/../shared/proactive'
vi.mock('@/api/client', () => ({ proactiveClient: {} }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => ({ activeWorkspaceId: 'A' }) }))
import { createProactiveControls } from './useProactiveControls'
const settings = (workspaceId = 'A', revision = 2) => ({
  ...createFailClosedProactiveSettings(), workspaceId, revision, enabled: true, dnd: false,
  sourceEnabled: { completed_turn_followup: true },
})
const frame = (workspaceId = 'A'): ActivityFrameSummary => ({
  frameId: 'frame', workspaceId, sessionId: 'session', sourceKind: 'completed_turn_followup',
  sourceId: 'source', sourceEventId: 'event', sourceCreatedAt: 1, createdAt: 1, expiresAt: 100,
  projectionVersion: 'v1', policyVersion: 'v1', authoritative: false, allowedActions: [],
})
const opportunity: ProactiveOpportunityIdentity = {
  jobId: 'job', requestId: 'request', frameId: 'frame', sourceKind: 'completed_turn_followup',
  sourceId: 'source', triggerReason: 'completed_turn_followup', expiresAt: 100,
}
const summary = (workspaceId = 'A'): ProactiveFeedbackSummary => ({
  schemaVersion: 'yuizaki.proactive-feedback-summary.v1', workspaceId, sourceKind: null,
  counts: {}, total: 0, behavioralTotal: 0, acceptanceRate: null, categoryPreferenceScores: {},
})
const setup = () => {
  let workspace = 'A'
  const api = {
    settings: vi.fn(async () => settings(workspace)),
    updateSettings: vi.fn(async () => ({ ...settings(workspace, 3), dnd: true })),
    frames: vi.fn(async (): Promise<ActivityFrameSummary[]> => [frame(workspace)]),
    rebuildFrames: vi.fn(async () => ({ workspaceId: workspace, projected: 1, tombstoned: 0, projectionVersion: 'v1' })),
    deleteFrame: vi.fn(async () => ({ ok: true })), feedback: vi.fn(async () => ({ ok: true })),
    feedbackSummary: vi.fn(async () => summary(workspace)),
  }
  return { api, controls: createProactiveControls(api, () => workspace), switchTo: (next: string) => { workspace = next } }
}
describe('workspace proactive requests', () => {
  it('binds every operation to the selected workspace', async () => {
    const { api, controls } = setup(); await controls.load()
    expect(api.settings).toHaveBeenCalledWith('A'); expect(api.frames).toHaveBeenCalledWith('A')
    await controls.updateSettings({ dnd: true }); expect(api.updateSettings).toHaveBeenCalledWith({ dnd: true }, 2, 'A')
    await controls.deleteFrame('frame'); expect(api.deleteFrame).toHaveBeenCalledWith('frame', 'A')
    await controls.rebuildFrames(); expect(api.rebuildFrames).toHaveBeenCalledWith(1000, 'A')
    await controls.submitFeedback(opportunity, 'useful')
    expect(api.feedback).toHaveBeenCalledWith(expect.objectContaining({ feedback: 'useful' }), 'A')
    expect(api.feedbackSummary).toHaveBeenCalledWith('A')
  })
  it('preserves pending save when background authorization loads', async () => {
    const { api, controls } = setup(); await controls.load()
    const pending = Promise.withResolvers<ReturnType<typeof settings>>()
    api.updateSettings.mockReturnValueOnce(pending.promise)
    const save = controls.updateSettings({ dnd: true })
    expect(await controls.load()).toBe(false); expect(controls.saving.value).toBe(true)
    expect(controls.settings.value.dnd).toBe(true); expect(api.settings).toHaveBeenCalledTimes(1)
    pending.resolve({ ...settings('A', 3), dnd: true }); expect(await save).toBe(true)
    expect(controls.settings.value).toMatchObject({ revision: 3, dnd: true }); expect(controls.saving.value).toBe(false)
  })
  it('does not submit a second write against a pending revision', async () => {
    const { api, controls } = setup(); await controls.load()
    const pending = Promise.withResolvers<ReturnType<typeof settings>>()
    api.updateSettings.mockReturnValueOnce(pending.promise)
    const save = controls.updateSettings({ dnd: true })
    expect(await controls.updateSettings({ dailyBudget: 3 })).toBe(false); expect(api.updateSettings).toHaveBeenCalledTimes(1)
    pending.resolve({ ...settings('A', 3), dnd: true }); await save
  })
  it.each(['load', 'updateSettings'] as const)('invalidation releases %s and rejects late response', async operation => {
    const { api, controls } = setup(); await controls.load()
    const pending = Promise.withResolvers<ReturnType<typeof settings>>()
    if (operation === 'load') api.settings.mockReturnValueOnce(pending.promise)
    else api.updateSettings.mockReturnValueOnce(pending.promise)
    const task = operation === 'load' ? controls.load() : controls.updateSettings({ dnd: true })
    controls.invalidate(); expect(controls.loading.value).toBe(false)
    expect(controls.saving.value).toBe(operation === 'updateSettings')
    expect(controls.loaded.value).toBe(false); expect(controls.policyClosed.value).toBe(true)
    pending.resolve(settings()); expect(await task).toBe(false)
    if (operation === 'load') expect(controls.loaded.value).toBe(false)
    else expect(controls.saving.value).toBe(false)
  })
  it('keeps latest load busy after old request finishes', async () => {
    const { api, controls } = setup()
    const first = Promise.withResolvers<ReturnType<typeof settings>>(), second = Promise.withResolvers<ReturnType<typeof settings>>()
    api.settings.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const a = controls.load(), b = controls.load()
    first.resolve(settings()); expect(await a).toBe(false); expect(controls.loading.value).toBe(true)
    second.resolve(settings()); expect(await b).toBe(true); expect(controls.loading.value).toBe(false)
  })
  it('commits main data without waiting for optional summary', async () => {
    const { api, controls } = setup(); const pending = Promise.withResolvers<ProactiveFeedbackSummary>()
    api.feedbackSummary.mockReturnValueOnce(pending.promise)
    expect(await controls.load()).toBe(true); expect(controls.loading.value).toBe(false)
    expect(controls.loaded.value).toBe(true); expect(controls.frames.value).toHaveLength(1)
    expect(controls.feedbackSummary.value).toBeNull()
    pending.resolve(summary()); await Promise.resolve(); await Promise.resolve()
    expect(controls.feedbackSummary.value?.workspaceId).toBe('A')
  })
  it('ignores previous workspace summary', async () => {
    const { api, controls, switchTo } = setup(); const pending = Promise.withResolvers<ProactiveFeedbackSummary>()
    api.feedbackSummary.mockReturnValueOnce(pending.promise)
    await controls.load(); switchTo('B'); await controls.load()
    pending.resolve(summary('A')); await Promise.resolve(); await Promise.resolve()
    expect(controls.feedbackSummary.value?.workspaceId).toBe('B')
  })
  it('does not apply old never_source feedback to the new workspace', async () => {
    const { api, controls, switchTo } = setup(); await controls.load()
    const pending = Promise.withResolvers<{ ok: boolean }>(); api.feedback.mockReturnValueOnce(pending.promise)
    const task = controls.submitFeedback(opportunity, 'never_source')
    switchTo('B'); await controls.load(); pending.resolve({ ok: true })
    expect(await task).toBe(false); expect(controls.settings.value.sourceEnabled.completed_turn_followup).toBe(true)
    expect(controls.acknowledgedFeedback.value.size).toBe(0)
  })
  it('ignores deletion errors after switching without explicit invalidation', async () => {
    const { api, controls, switchTo } = setup(); await controls.load()
    const pending = Promise.withResolvers<{ ok: boolean }>(); api.deleteFrame.mockReturnValueOnce(pending.promise)
    const task = controls.deleteFrame('frame'); switchTo('B'); await controls.load()
    pending.reject(new Error('A delete failed')); expect(await task).toBe(false)
    expect(controls.loaded.value).toBe(true); expect(controls.policyClosed.value).toBe(false)
    expect(controls.error.value).toBeNull(); expect(controls.visibleFrames.value).toHaveLength(1)
  })
  it.each(['rejected', 'thrown'] as const)('restores hidden frame after %s deletion failure', async mode => {
    const { api, controls } = setup(); await controls.load()
    if (mode === 'rejected') api.deleteFrame.mockResolvedValueOnce({ ok: false })
    else api.deleteFrame.mockRejectedValueOnce(new Error('delete failed'))
    expect(await controls.deleteFrame('frame')).toBe(false); expect(controls.visibleFrames.value).toHaveLength(1)
    await controls.load(); expect(controls.visibleFrames.value).toHaveLength(1)
  })
  it('ignores old workspace rebuild completion and releases lock', async () => {
    const { api, controls, switchTo } = setup(); await controls.load()
    const pending = Promise.withResolvers<Awaited<ReturnType<typeof api.rebuildFrames>>>()
    api.rebuildFrames.mockReturnValueOnce(pending.promise); const task = controls.rebuildFrames()
    switchTo('B'); await controls.load(); expect(controls.rebuilding.value).toBe(false)
    const reads = api.settings.mock.calls.length
    pending.resolve({ workspaceId: 'A', projected: 1, tombstoned: 0, projectionVersion: 'v1' })
    expect(await task).toBe(false); expect(api.settings).toHaveBeenCalledTimes(reads)
    expect(controls.settings.value.workspaceId).toBe('B')
  })
  it('clears private snapshots on invalidation and rejects mismatched settings', async () => {
    const { api, controls } = setup(); await controls.load(); controls.invalidate()
    expect(controls.frames.value).toEqual([]); expect(controls.feedbackSummary.value).toBeNull()
    api.settings.mockResolvedValueOnce(settings('B')); expect(await controls.load()).toBe(false)
    expect(controls.loaded.value).toBe(false)
  })
  it('keeps A policy closed after A to B to A while its original save is pending', async () => {
    const { api, controls, switchTo } = setup(); await controls.load()
    const pending = Promise.withResolvers<ReturnType<typeof settings>>()
    api.updateSettings.mockReturnValueOnce(pending.promise)
    const save = controls.updateSettings({ dnd: true })
    switchTo('B'); await controls.load(); switchTo('A')
    expect(await controls.load()).toBe(false)
    expect(controls.saving.value).toBe(true)
    expect(controls.policyClosed.value).toBe(true)
    api.settings.mockResolvedValueOnce({ ...settings('A', 3), dnd: true })
    pending.resolve({ ...settings('A', 3), dnd: true }); expect(await save).toBe(false)
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(controls.settings.value).toMatchObject({ workspaceId: 'A', revision: 3, dnd: true })
    expect(controls.saving.value).toBe(false)
  })
  it('serializes never_source feedback with settings writes and reads back its revision', async () => {
    const { api, controls } = setup(); await controls.load()
    const pending = Promise.withResolvers<ReturnType<typeof settings>>()
    api.updateSettings.mockReturnValueOnce(pending.promise)
    const save = controls.updateSettings({ dnd: true })
    expect(await controls.submitFeedback(opportunity, 'never_source')).toBe(false)
    expect(api.feedback).not.toHaveBeenCalled()
    pending.resolve({ ...settings('A', 3), dnd: true }); await save
    const feedback = Promise.withResolvers<{ ok: boolean }>()
    api.feedback.mockReturnValueOnce(feedback.promise)
    const submitted = controls.submitFeedback(opportunity, 'never_source')
    expect(await controls.updateSettings({ dailyBudget: 3 })).toBe(false)
    api.settings.mockResolvedValueOnce({ ...settings('A', 4), sourceEnabled: { completed_turn_followup: false } })
    feedback.resolve({ ok: true }); expect(await submitted).toBe(true)
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(controls.settings.value).toMatchObject({ revision: 4, sourceEnabled: { completed_turn_followup: false } })
  })
  it('rejects a snapshot started before never_source feedback and keeps policy closed until readback', async () => {
    const { api, controls } = setup(); await controls.load()
    const snapshot = Promise.withResolvers<ReturnType<typeof settings>>()
    const feedback = Promise.withResolvers<{ ok: boolean }>()
    api.settings.mockReturnValueOnce(snapshot.promise)
    const refresh = controls.load()
    api.feedback.mockReturnValueOnce(feedback.promise)
    const submitted = controls.submitFeedback(opportunity, 'never_source')
    snapshot.resolve(settings())
    expect(await refresh).toBe(false)
    expect(controls.policyClosed.value).toBe(true)
    expect(controls.loading.value).toBe(false)
    expect(controls.saving.value).toBe(true)
    expect(controls.allows('completed_turn_followup')).toBe(false)
    api.settings.mockResolvedValueOnce({ ...settings('A', 3), sourceEnabled: { completed_turn_followup: false } })
    feedback.resolve({ ok: true }); expect(await submitted).toBe(true)
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(controls.settings.value).toMatchObject({ revision: 3, sourceEnabled: { completed_turn_followup: false } })
  })

})

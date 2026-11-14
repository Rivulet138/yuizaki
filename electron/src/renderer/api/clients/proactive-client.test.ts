import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createFailClosedProactiveSettings, type ProactiveFeedbackRequest } from '@/../shared/proactive'
const { requestJson } = vi.hoisted(() => ({ requestJson: vi.fn() }))
vi.mock('./http-client', () => ({ CONTROL_ORIGIN: 'http://localhost:48001', requestJson }))
import { proactiveClient } from './proactive-client'
const workspace = 'workspace A/&'
const query = '?workspace_id=workspace%20A%2F%26'
const settings = () => ({ ...createFailClosedProactiveSettings(), workspaceId: workspace, policyVersion: 'v1' })
const feedback: ProactiveFeedbackRequest = {
  jobId: 'job', requestId: 'request', frameId: 'frame', sourceKind: 'completed_turn_followup',
  sourceId: 'source', triggerReason: 'completed_turn_followup', expiresAt: 100,
  feedbackId: 'feedback', feedback: 'useful',
}
describe('proactive API workspace identity', () => {
  beforeEach(() => requestJson.mockReset())
  it('scopes settings reads and writes, retaining revision and patch', async () => {
    requestJson.mockResolvedValue(settings())
    await proactiveClient.settings(workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/proactive/settings' + query)
    await proactiveClient.updateSettings({ dnd: true }, 3, workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/proactive/settings' + query, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expectedRevision: 3, dnd: true }),
    })
  })
  it('scopes frames, rebuild and encoded frame deletion', async () => {
    requestJson.mockResolvedValue({ schemaVersion: 'yuizaki.activity-frame.v1', frames: [] })
    await proactiveClient.frames(workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/activity-frames' + query)
    requestJson.mockResolvedValue({ workspaceId: workspace, projected: 1, tombstoned: 0, projectionVersion: 'v1' })
    await proactiveClient.rebuildFrames(1000, workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/activity-frames/rebuild' + query, expect.objectContaining({ body: '{"limit":1000}', method: 'POST' }))
    requestJson.mockResolvedValue({ ok: true })
    await proactiveClient.deleteFrame('frame/?', workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/activity-frames/frame%2F%3F' + query, { method: 'DELETE' })
  })
  it('scopes feedback and advisory summary without changing feedback payload', async () => {
    requestJson.mockResolvedValue({ ok: true })
    await proactiveClient.feedback(feedback, workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/proactive/feedback' + query, expect.objectContaining({
      method: 'POST', body: JSON.stringify({ feedbackId: 'feedback', jobId: 'job', requestId: 'request', sourceKind: 'completed_turn_followup', kind: 'useful' }),
    }))
    requestJson.mockResolvedValue({ schemaVersion: 'yuizaki.proactive-feedback-summary.v1', workspaceId: workspace, sourceKind: null, counts: {}, total: 0, behavioralTotal: 0, acceptanceRate: null, categoryPreferenceScores: {} })
    await proactiveClient.feedbackSummary(workspace)
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:48001/api/system/proactive/feedback-summary' + query)
  })
  it('rejects blank workspace before sending a request', async () => {
    await expect(proactiveClient.updateSettings({ dnd: true }, 0, ' ')).rejects.toThrow('workspace_id_required')
    expect(requestJson).not.toHaveBeenCalled()
  })
})

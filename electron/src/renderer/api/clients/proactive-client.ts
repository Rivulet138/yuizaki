import {
  parseActivityFrames,
  parseProactiveSettings,
  parseProactiveFeedbackSummary,
  serializeProactiveFeedback,
  serializeProactiveSettingsPatch,
  type ActivityFrameSummary,
  type ProactiveFeedbackRequest,
  type ProactiveSettings,
  type ProactiveSettingsPatch,
  type ProactiveFeedbackSummary,
} from '@/../shared/proactive'
import { CONTROL_ORIGIN, requestJson } from './http-client'

export interface ActivityFrameRebuildResult {
  workspaceId: string
  projected: number
  tombstoned: number
  projectionVersion: string
}

const requireSettings = (value: unknown): ProactiveSettings => {
  const parsed = parseProactiveSettings(value)
  if (!parsed) throw new Error('invalid_proactive_settings')
  return parsed
}

const requireFrames = (value: unknown): ActivityFrameSummary[] => {
  const parsed = parseActivityFrames(value)
  if (!parsed) throw new Error('invalid_activity_frames')
  return parsed
}

const scopedUrl = (path: string, workspaceId: string): string => {
  if (!workspaceId.trim()) throw new Error('workspace_id_required')
  return `${CONTROL_ORIGIN}${path}?workspace_id=${encodeURIComponent(workspaceId)}`
}

export const proactiveClient = {
  settings: async (workspaceId: string): Promise<ProactiveSettings> => requireSettings(
    await requestJson<unknown>(scopedUrl('/api/system/proactive/settings', workspaceId)),
  ),
  updateSettings: async (patch: ProactiveSettingsPatch, expectedRevision: number, workspaceId: string): Promise<ProactiveSettings> => requireSettings(
    await requestJson<unknown>(scopedUrl('/api/system/proactive/settings', workspaceId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeProactiveSettingsPatch(patch, expectedRevision)),
    }),
  ),
  frames: async (workspaceId: string): Promise<ActivityFrameSummary[]> => requireFrames(
    await requestJson<unknown>(scopedUrl('/api/system/activity-frames', workspaceId)),
  ),
  rebuildFrames: async (limit: number, workspaceId: string): Promise<ActivityFrameRebuildResult> => requestJson<ActivityFrameRebuildResult>(
    scopedUrl('/api/system/activity-frames/rebuild', workspaceId),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit }),
    },
  ),
  deleteFrame: async (frameId: string, workspaceId: string): Promise<{ ok: boolean }> => requestJson<{ ok: boolean }>(
    scopedUrl(`/api/system/activity-frames/${encodeURIComponent(frameId)}`, workspaceId),
    { method: 'DELETE' },
  ),
  feedback: async (payload: ProactiveFeedbackRequest, workspaceId: string): Promise<{ ok: boolean }> => requestJson<{ ok: boolean }>(
    scopedUrl('/api/system/proactive/feedback', workspaceId),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeProactiveFeedback(payload)),
    },
  ),
  feedbackSummary: async (workspaceId: string): Promise<ProactiveFeedbackSummary> => {
    const parsed = parseProactiveFeedbackSummary(
      await requestJson<unknown>(scopedUrl('/api/system/proactive/feedback-summary', workspaceId)),
    )
    if (!parsed) throw new Error('invalid_proactive_feedback_summary')
    return parsed
  },
}

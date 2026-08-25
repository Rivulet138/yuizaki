import {
  parseActivityFrames,
  parseProactiveSettings,
  serializeProactiveFeedback,
  serializeProactiveSettingsPatch,
  type ActivityFrameSummary,
  type ProactiveFeedbackRequest,
  type ProactiveSettings,
  type ProactiveSettingsPatch,
} from '@/../shared/proactive'
import { CONTROL_ORIGIN, requestJson } from './http-client'

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

export const proactiveClient = {
  settings: async (): Promise<ProactiveSettings> => requireSettings(
    await requestJson<unknown>(`${CONTROL_ORIGIN}/api/system/proactive/settings`),
  ),
  updateSettings: async (patch: ProactiveSettingsPatch, expectedRevision: number): Promise<ProactiveSettings> => requireSettings(
    await requestJson<unknown>(`${CONTROL_ORIGIN}/api/system/proactive/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeProactiveSettingsPatch(patch, expectedRevision)),
    }),
  ),
  frames: async (): Promise<ActivityFrameSummary[]> => requireFrames(
    await requestJson<unknown>(`${CONTROL_ORIGIN}/api/system/activity-frames`),
  ),
  deleteFrame: async (frameId: string): Promise<{ ok: boolean }> => requestJson<{ ok: boolean }>(
    `${CONTROL_ORIGIN}/api/system/activity-frames/${encodeURIComponent(frameId)}`,
    { method: 'DELETE' },
  ),
  feedback: async (payload: ProactiveFeedbackRequest): Promise<{ ok: boolean }> => requestJson<{ ok: boolean }>(
    `${CONTROL_ORIGIN}/api/system/proactive/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeProactiveFeedback(payload)),
    },
  ),
}

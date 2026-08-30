export const PROACTIVE_SOURCES = ['completed_turn_followup'] as const
export type ProactiveSource = typeof PROACTIVE_SOURCES[number]

export const PROACTIVE_CONTENT_CODES = ['completed_turn_followup'] as const
export type ProactiveContentCode = typeof PROACTIVE_CONTENT_CODES[number]

export const PROACTIVE_SETTINGS_LIMITS = {
  dailyBudget: { min: 1, max: 20 },
  cooldownSeconds: { min: 0, max: 604_800 },
  retentionDays: { min: 1, max: 90 },
} as const

export const PROACTIVE_FEEDBACK_KINDS = ['useful', 'not_useful', 'too_frequent', 'wrong_time', 'never_source'] as const
export type ProactiveFeedbackKind = typeof PROACTIVE_FEEDBACK_KINDS[number] | 'snoozed'

export interface ProactiveQuietHours {
  enabled: boolean
  start: string
  end: string
  timezone: string
}

export interface ProactiveSettings {
  schemaVersion: 'yuizaki.proactive-settings.v1'
  workspaceId: string
  revision: number
  updatedAt: number | null
  enabled: boolean
  sourceEnabled: Record<ProactiveSource, boolean>
  dnd: boolean
  quietHours: ProactiveQuietHours
  dailyBudget: number
  cooldownSeconds: number
  retentionDays: number
  policyVersion: string
}

export interface ProactiveSettingsPatch {
  enabled?: boolean
  sourceEnabled?: Partial<Record<ProactiveSource, boolean>>
  dnd?: boolean
  quietHours?: Partial<ProactiveQuietHours>
  dailyBudget?: number
  cooldownSeconds?: number
  retentionDays?: number
}

export interface ActivityFrameSummary {
  frameId: string
  workspaceId: string
  sessionId: string
  sourceKind: ProactiveSource
  sourceId: string
  sourceEventId: string
  sourceCreatedAt: number
  createdAt: number
  expiresAt: number
  projectionVersion: string
  policyVersion: string
  authoritative: false
  allowedActions: []
}

export interface ProactiveOpportunityIdentity {
  jobId: string
  requestId: string
  sourceKind: ProactiveSource
  sourceId: string
  triggerReason: string
  expiresAt: number
  frameId: string
}

export interface ProactiveFeedbackRequest extends ProactiveOpportunityIdentity {
  feedbackId: string
  feedback: ProactiveFeedbackKind
}

export interface ProactiveFeedbackSummary {
  schemaVersion: 'yuizaki.proactive-feedback-summary.v1'
  workspaceId: string
  sourceKind: ProactiveSource | string | null
  counts: Record<string, number>
  total: number
  behavioralTotal: number
  acceptanceRate: number | null
  categoryPreferenceScores: Record<string, number>
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const read = (record: Record<string, unknown>, camel: string, snake: string): unknown => record[camel] ?? record[snake]
const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
const isNonEmptyString = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
const isNonNegativeNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0
const isNonNegativeInteger = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0
const isClockTime = (value: unknown): value is string => isNonEmptyString(value) && /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
const isIntegerWithin = (value: unknown, limits: { min: number; max: number }): value is number =>
  Number.isSafeInteger(value) && Number(value) >= limits.min && Number(value) <= limits.max

const localMinute = (epochMillis: number, timezone: string): number | null => {
  if (!Number.isFinite(epochMillis) || !isNonEmptyString(timezone)) return null
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(new Date(epochMillis))
    const hour = Number(parts.find((part) => part.type === 'hour')?.value)
    const minute = Number(parts.find((part) => part.type === 'minute')?.value)
    if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 24 || minute < 0 || minute > 59) return null
    return (hour % 24) * 60 + minute
  } catch {
    return null
  }
}

export const isProactiveQuietHoursClear = (
  quietHours: ProactiveQuietHours,
  epochMillis: number = Date.now(),
): boolean => {
  const minute = localMinute(epochMillis, quietHours.timezone)
  if (minute === null || !isClockTime(quietHours.start) || !isClockTime(quietHours.end)) return false
  if (!quietHours.enabled) return true
  const [startHour = 0, startMinute = 0] = quietHours.start.split(':').map(Number)
  const [endHour = 0, endMinute = 0] = quietHours.end.split(':').map(Number)
  const start = startHour * 60 + startMinute
  const end = endHour * 60 + endMinute
  const isQuiet = start === end
    || (start < end ? start <= minute && minute < end : minute >= start || minute < end)
  return !isQuiet
}

export const isProactiveSource = (value: unknown): value is ProactiveSource =>
  typeof value === 'string' && (PROACTIVE_SOURCES as readonly string[]).includes(value)

export const isProactiveContentCode = (value: unknown): value is ProactiveContentCode =>
  typeof value === 'string' && (PROACTIVE_CONTENT_CODES as readonly string[]).includes(value)

export const createFailClosedProactiveSettings = (): ProactiveSettings => ({
  schemaVersion: 'yuizaki.proactive-settings.v1',
  workspaceId: '',
  revision: 0,
  updatedAt: null,
  enabled: false,
  sourceEnabled: { completed_turn_followup: false },
  dnd: true,
  quietHours: { enabled: true, start: '00:00', end: '00:00', timezone: 'UTC' },
  dailyBudget: PROACTIVE_SETTINGS_LIMITS.dailyBudget.min,
  cooldownSeconds: 86_400,
  retentionDays: 1,
  policyVersion: '',
})

export const parseProactiveSettings = (value: unknown): ProactiveSettings | null => {
  const envelope = isRecord(value) && isRecord(value['settings']) ? value['settings'] : value
  if (!isRecord(envelope)) return null
  const sourceEnabled = read(envelope, 'sourceEnabled', 'source_enabled')
  const quietHours = read(envelope, 'quietHours', 'quiet_hours')
  if (!isRecord(sourceEnabled) || !isRecord(quietHours)) return null
  const schemaVersion = read(envelope, 'schemaVersion', 'schema_version')
  const workspaceId = read(envelope, 'workspaceId', 'workspace_id')
  const revision = envelope['revision']
  const updatedAt = read(envelope, 'updatedAt', 'updated_at')
  const enabled = envelope['enabled']
  const completedTurnFollowup = sourceEnabled['completed_turn_followup']
  const dnd = envelope['dnd']
  const quietEnabled = quietHours['enabled']
  const quietStart = quietHours['start']
  const quietEnd = quietHours['end']
  const timezone = quietHours['timezone']
  const dailyBudget = read(envelope, 'dailyBudget', 'daily_budget')
  const cooldownSeconds = read(envelope, 'cooldownSeconds', 'cooldown_seconds')
  const retentionDays = read(envelope, 'retentionDays', 'retention_days')
  const policyVersion = read(envelope, 'policyVersion', 'policy_version')
  if (schemaVersion !== 'yuizaki.proactive-settings.v1'
    || !isNonEmptyString(workspaceId)
    || !isNonNegativeInteger(revision)
    || !(updatedAt === null || isNonNegativeNumber(updatedAt))
    || !isBoolean(enabled)
    || !isBoolean(completedTurnFollowup)
    || !isBoolean(dnd)
    || !isBoolean(quietEnabled)
    || !isClockTime(quietStart)
    || !isClockTime(quietEnd)
    || !isNonEmptyString(timezone)
    || localMinute(0, timezone) === null
    || !isIntegerWithin(dailyBudget, PROACTIVE_SETTINGS_LIMITS.dailyBudget)
    || !isIntegerWithin(cooldownSeconds, PROACTIVE_SETTINGS_LIMITS.cooldownSeconds)
    || !isIntegerWithin(retentionDays, PROACTIVE_SETTINGS_LIMITS.retentionDays)
    || !isNonEmptyString(policyVersion)) return null
  return {
    schemaVersion,
    workspaceId,
    revision,
    updatedAt,
    enabled,
    sourceEnabled: { completed_turn_followup: completedTurnFollowup },
    dnd,
    quietHours: { enabled: quietEnabled, start: quietStart, end: quietEnd, timezone },
    dailyBudget,
    cooldownSeconds,
    retentionDays,
    policyVersion,
  }
}

const parseFrame = (value: unknown): ActivityFrameSummary | null => {
  if (!isRecord(value)) return null
  const frameId = read(value, 'frameId', 'frame_id')
  const workspaceId = read(value, 'workspaceId', 'workspace_id')
  const sessionId = read(value, 'sessionId', 'session_id')
  const sourceKind = read(value, 'sourceKind', 'source_kind')
  const sourceId = read(value, 'sourceId', 'source_id')
  const sourceEventId = read(value, 'sourceEventId', 'source_event_id')
  const sourceCreatedAt = read(value, 'sourceCreatedAt', 'source_created_at')
  const createdAt = read(value, 'createdAt', 'created_at')
  const expiresAt = read(value, 'expiresAt', 'expires_at')
  const projectionVersion = read(value, 'projectionVersion', 'projection_version')
  const policyVersion = read(value, 'policyVersion', 'policy_version')
  const allowedActions = read(value, 'allowedActions', 'allowed_actions')
  if (!isNonEmptyString(frameId)
    || !isNonEmptyString(workspaceId)
    || !isNonEmptyString(sessionId)
    || !isProactiveSource(sourceKind)
    || !isNonEmptyString(sourceId)
    || !isNonEmptyString(sourceEventId)
    || !isNonNegativeNumber(sourceCreatedAt)
    || !isNonNegativeNumber(createdAt)
    || !isNonNegativeNumber(expiresAt)
    || !isNonEmptyString(projectionVersion)
    || !isNonEmptyString(policyVersion)
    || value['authoritative'] !== false
    || !Array.isArray(allowedActions)
    || allowedActions.length !== 0) return null
  return {
    frameId,
    workspaceId,
    sessionId,
    sourceKind,
    sourceId,
    sourceEventId,
    sourceCreatedAt,
    createdAt,
    expiresAt,
    projectionVersion,
    policyVersion,
    authoritative: false,
    allowedActions: [],
  }
}

export const parseActivityFrames = (value: unknown): ActivityFrameSummary[] | null => {
  const envelope = isRecord(value) && value['schemaVersion'] === 'yuizaki.activity-frame.v1' ? value : null
  const items = envelope && Array.isArray(envelope['frames']) ? envelope['frames'] : null
  if (!items) return null
  const parsed = items.map(parseFrame)
  return parsed.every((item): item is ActivityFrameSummary => item !== null) ? parsed : null
}

export const parseProactiveFeedbackSummary = (value: unknown): ProactiveFeedbackSummary | null => {
  if (!isRecord(value)
    || value['schemaVersion'] !== 'yuizaki.proactive-feedback-summary.v1'
    || !isNonEmptyString(value['workspaceId'])
    || !(value['sourceKind'] === null || isNonEmptyString(value['sourceKind']))
    || !isRecord(value['counts'])
    || !isRecord(value['categoryPreferenceScores'])) return null
  const boundedCounts: Record<string, number> = {}
  for (const [key, count] of Object.entries(value['counts'])) {
    if (isNonEmptyString(key) && isIntegerWithin(count, { min: 0, max: 500 })) boundedCounts[key] = count
  }
  const categoryScores: Record<string, number> = {}
  for (const [key, score] of Object.entries(value['categoryPreferenceScores'])) {
    if (isNonEmptyString(key) && typeof score === 'number' && Number.isFinite(score) && score >= -500 && score <= 500) {
      categoryScores[key] = score
    }
  }
  const total = value['total']
  const behavioralTotal = value['behavioralTotal']
  const acceptanceRate = value['acceptanceRate']
  if (!isIntegerWithin(total, { min: 0, max: 500 })
    || !isIntegerWithin(behavioralTotal, { min: 0, max: 500 })
    || !(acceptanceRate === null || (typeof acceptanceRate === 'number' && Number.isFinite(acceptanceRate) && acceptanceRate >= 0 && acceptanceRate <= 1))) return null
  return {
    schemaVersion: 'yuizaki.proactive-feedback-summary.v1',
    workspaceId: value['workspaceId'],
    sourceKind: value['sourceKind'],
    counts: boundedCounts,
    total,
    behavioralTotal,
    acceptanceRate,
    categoryPreferenceScores: categoryScores,
  }
}

export const parseProactiveOpportunityIdentity = (value: unknown): ProactiveOpportunityIdentity | null => {
  if (!isRecord(value)) return null
  const jobId = read(value, 'jobId', 'job_id')
  const requestId = read(value, 'requestId', 'request_id')
  const sourceKind = read(value, 'sourceKind', 'source_kind')
  const sourceId = read(value, 'sourceId', 'source_id')
  const triggerReason = read(value, 'triggerReason', 'trigger_reason')
  const expiresAt = read(value, 'expiresAt', 'expires_at')
  const frameId = read(value, 'frameId', 'frame_id') ?? value['activity_frame_id']
  if (!isNonEmptyString(jobId)
    || !isNonEmptyString(requestId)
    || !isProactiveSource(sourceKind)
    || !isNonEmptyString(sourceId)
    || !isNonEmptyString(triggerReason)
    || typeof expiresAt !== 'number'
    || !Number.isFinite(expiresAt)
    || expiresAt <= 0
    || !isNonEmptyString(frameId)) return null
  return { jobId, requestId, sourceKind, sourceId, triggerReason, expiresAt, frameId }
}

export const serializeProactiveSettingsPatch = (
  patch: ProactiveSettingsPatch,
  expectedRevision: number,
): Record<string, unknown> => {
  if ((patch.dailyBudget !== undefined && !isIntegerWithin(patch.dailyBudget, PROACTIVE_SETTINGS_LIMITS.dailyBudget))
    || (patch.cooldownSeconds !== undefined && !isIntegerWithin(patch.cooldownSeconds, PROACTIVE_SETTINGS_LIMITS.cooldownSeconds))
    || (patch.retentionDays !== undefined && !isIntegerWithin(patch.retentionDays, PROACTIVE_SETTINGS_LIMITS.retentionDays))) {
    throw new Error('invalid_proactive_settings_patch')
  }
  return {
    expectedRevision,
    ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}),
    ...(patch.sourceEnabled ? { sourceEnabled: patch.sourceEnabled } : {}),
    ...(patch.dnd !== undefined ? { dnd: patch.dnd } : {}),
    ...(patch.quietHours ? { quietHours: patch.quietHours } : {}),
    ...(patch.dailyBudget !== undefined ? { dailyBudget: patch.dailyBudget } : {}),
    ...(patch.cooldownSeconds !== undefined ? { cooldownSeconds: patch.cooldownSeconds } : {}),
    ...(patch.retentionDays !== undefined ? { retentionDays: patch.retentionDays } : {}),
  }
}

export const serializeProactiveFeedback = (payload: ProactiveFeedbackRequest): Record<string, unknown> => ({
  feedbackId: payload.feedbackId,
  jobId: payload.jobId,
  requestId: payload.requestId,
  sourceKind: payload.sourceKind,
  kind: payload.feedback,
})

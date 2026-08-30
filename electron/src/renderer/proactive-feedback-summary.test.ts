import { describe, expect, it } from 'vitest'
import { parseProactiveFeedbackSummary, serializeProactiveFeedback } from '@/../shared/proactive'

describe('parseProactiveFeedbackSummary', () => {
  it('accepts bounded telemetry and preserves category scores', () => {
    expect(parseProactiveFeedbackSummary({
      schemaVersion: 'yuizaki.proactive-feedback-summary.v1',
      workspaceId: 'workspace-1',
      sourceKind: 'completed_turn_followup',
      counts: { accepted: 2, ignored: 1 },
      total: 3,
      behavioralTotal: 3,
      acceptanceRate: 2 / 3,
      categoryPreferenceScores: { general: -0.25 },
    })).toMatchObject({
      workspaceId: 'workspace-1',
      total: 3,
      categoryPreferenceScores: { general: -0.25 },
    })
  })

  it('rejects malformed summary metadata and unbounded totals', () => {
    expect(parseProactiveFeedbackSummary({
      schemaVersion: 'yuizaki.proactive-feedback-summary.v1',
      workspaceId: 'workspace-1',
      sourceKind: null,
      counts: {},
      total: 501,
      behavioralTotal: 0,
      acceptanceRate: null,
      categoryPreferenceScores: {},
    })).toBeNull()
    expect(parseProactiveFeedbackSummary({
      schemaVersion: 'yuizaki.proactive-feedback-summary.v1',
      workspaceId: 'workspace-1',
      sourceKind: null,
      counts: { accepted: Number.NaN },
      total: 0,
      behavioralTotal: 0,
      acceptanceRate: 1.5,
      categoryPreferenceScores: {},
    })).toBeNull()
  })

  it('serializes the user snooze action accepted by the backend', () => {
    expect(serializeProactiveFeedback({
      feedbackId: 'feedback-1',
      jobId: 'job-1',
      requestId: 'request-1',
      sourceKind: 'completed_turn_followup',
      sourceId: 'source-1',
      triggerReason: 'completed_turn_followup',
      expiresAt: 1_800_000_000,
      frameId: 'frame-1',
      feedback: 'snoozed',
    })).toMatchObject({ kind: 'snoozed' })
  })
})

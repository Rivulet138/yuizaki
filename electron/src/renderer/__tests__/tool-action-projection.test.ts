import { describe, expect, it } from 'vitest'
import {
  projectToolActionStatus,
  toolActionStatusLabel,
  toolEvidenceFromRecord,
} from '@/domains/tools/toolActionProjection'

describe('tool action projection', () => {
  it('uses closed completion and verification states', () => {
    expect(projectToolActionStatus('ok')).toBe('completed')
    expect(projectToolActionStatus('success')).toBe('completed')
    expect(projectToolActionStatus('completed', 'unverified')).toBe('completed')
    expect(projectToolActionStatus('completed', 'verified')).toBe('verified')
    expect(projectToolActionStatus('failed', 'verified')).toBe('failed')
    expect(projectToolActionStatus('unknown_effect')).toBe('unknown_effect')
    expect(toolActionStatusLabel('completed')).toBe('已完成（未验证）')
  })

  it('redacts evidence before display', () => {
    const evidence = toolEvidenceFromRecord({
      verificationEvidence: ['Authorization: Bearer visible-secret'],
    })
    expect(evidence[0]).not.toContain('visible-secret')
    expect(evidence[0]).toContain('[redacted]')
  })
})


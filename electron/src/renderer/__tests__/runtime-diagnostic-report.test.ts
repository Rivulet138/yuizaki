import { describe, expect, it } from 'vitest'
import {
  createRuntimeDiagnosticReport,
  projectRuntimeDiagnosticReport,
  serializeRuntimeDiagnosticReport,
} from '@/app/runtime/runtimeDiagnosticReport'

describe('runtime diagnostic report', () => {
  it('keeps only numeric, boolean, and closed-set state values', () => {
    const report = createRuntimeDiagnosticReport({
      provider: { status: 'healthy', latencyMs: 42, model: 'private-model', apiKey: 'secret' },
      voice: { available: true, firstAudioMs: 180, transcript: 'do not export' },
      jobs: [{ status: 'unknown_effect', attempts: 2, jobId: 'job-secret' }],
      panelUrl: 'C:\\private\\panel',
    })
    expect(report).toEqual({
      schemaVersion: 1,
      report: {
        provider: { status: 'healthy', latencyMs: 42 },
        voice: { available: true, firstAudioMs: 180 },
        jobs: [{ status: 'unknown_effect', attempts: 2 }],
      },
    })
  })

  it('normalizes unknown status strings and removes nested sensitive values', () => {
    const projected = projectRuntimeDiagnosticReport({
      status: 'brand-new-state',
      nested: { state: 'running', tokenCount: 4, account: { connected: true } },
      evidence: { success: true },
    })
    expect(projected).toEqual({ status: 'unknown', nested: { state: 'running' } })
    expect(JSON.stringify(projected)).not.toMatch(/brand-new|account|token|success/i)
  })

  it('serializes without introducing free-form text', () => {
    const result = serializeRuntimeDiagnosticReport(createRuntimeDiagnosticReport({ status: 'ready', count: 1 }))
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.json).toContain('"status": "ready"')
      expect(result.json).not.toMatch(/path|token|secret|account|private/i)
    }
  })

  it('still creates a useful report when some read-only sources are unavailable', () => {
    const report = createRuntimeDiagnosticReport({
      runtime: null,
      experience: { tools: { calls: 3, failures: 1 } },
      voice: null,
      collection: { requestedSourceCount: 4, successfulSourceCount: 2, failedSourceCount: 2 },
    })
    expect(report.report).toEqual({
      experience: { tools: { calls: 3, failures: 1 } },
      collection: { requestedSourceCount: 4, successfulSourceCount: 2, failedSourceCount: 2 },
    })
  })
})

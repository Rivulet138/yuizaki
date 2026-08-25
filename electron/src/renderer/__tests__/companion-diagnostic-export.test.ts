import { describe, expect, it } from 'vitest'
import {
  createRedactedDiagnosticBundle,
  serializeRedactedDiagnosticBundle,
} from '@/app/runtime/companionDiagnosticExport'

describe('companion diagnostic export', () => {
  it('redacts secret keys and secret-looking string values recursively', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        authorization: 'Bearer live-token-value',
        nested: { api_key: 'sk-live-provider-key', note: 'token=plain-secret' },
      },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain('live-token-value')
    expect(serialized).not.toContain('sk-live-provider-key')
    expect(serialized).not.toContain('plain-secret')
    expect(serialized).toContain('[redacted]')
  })

  it('omits raw screenshots, memory text, audio, and frame payloads', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        screenshot: 'data:image/png;base64,RAW_SCREEN',
        memoryText: 'private remembered sentence',
        pcm: 'RAW_PCM',
        frameData: 'RAW_FRAME',
        args: { content: 'raw tool argument' },
        messages: [{ content: 'raw conversation text' }],
        reply_preview: 'raw memory reply',
        summary: 'bounded public summary',
      },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain('RAW_SCREEN')
    expect(serialized).not.toContain('private remembered sentence')
    expect(serialized).not.toContain('RAW_PCM')
    expect(serialized).not.toContain('RAW_FRAME')
    expect(serialized).not.toContain('raw tool argument')
    expect(serialized).not.toContain('raw conversation text')
    expect(serialized).not.toContain('raw memory reply')
    expect(serialized).not.toContain('bounded public summary')
    expect(serialized).toContain('[omitted:sensitive-payload]')
  })

  it('omits user-authored query and prompt fields, including natural-language secrets', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        query: 'password is hunter2',
        prompt: 'Please use the access token is abc123 to sign in',
        input: 'secret is open-sesame',
        transcript: 'my api key is sk-live-user-content',
        summary: 'step failed',
      },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain('hunter2')
    expect(serialized).not.toContain('abc123')
    expect(serialized).not.toContain('open-sesame')
    expect(serialized).not.toContain('sk-live-user-content')
    expect(serialized).toContain('[omitted:sensitive-payload]')
  })

  it('redacts natural-language credential phrases in bounded labels', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: { summary: 'provider failed: password is hunter2' },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain('hunter2')
    expect(serialized).toContain('[omitted:sensitive-payload]')
  })

  it('fails closed to omitted markers for unrecognized future trace fields', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        status: 'failed',
        summary: 'arbitrary user secret: blue-lantern-42',
        futureFreeformPayload: 'private text without a recognizable secret pattern',
        data: { reply: 'echoed user credential material' },
      },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain('private text without a recognizable secret pattern')
    expect(serialized).not.toContain('blue-lantern-42')
    expect(serialized).not.toContain('echoed user credential material')
    expect(serialized).toContain('"status":"failed"')
    expect(serialized).toContain('[omitted:sensitive-payload]')
  })

  it('never exports arbitrary text through allowed metadata-shaped keys', () => {
    const secret = 'project-codename-blue-lantern-42'
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        requestId: secret,
        tool: secret,
        routeReason: secret,
        ownerRoles: [secret],
        status: secret,
        completedSteps: [secret],
        progress: 0.5,
      },
    })
    const serialized = JSON.stringify(bundle)

    expect(serialized).not.toContain(secret)
    expect(serialized).toContain('[id:1]')
    expect(serialized).toContain('[omitted:sensitive-payload]')
    expect(serialized).toContain('"progress":0.5')
  })

  it('retains only closed enum values and aliases repeated identifiers consistently', () => {
    const bundle = createRedactedDiagnosticBundle({
      trace: {
        status: 'failed',
        source: 'scheduler',
        requestId: 'request-private',
        failedStep: 'request-private',
      },
    })
    const diagnostics = bundle.diagnostics as { trace: Record<string, unknown> }

    expect(diagnostics.trace.status).toBe('failed')
    expect(diagnostics.trace.source).toBe('scheduler')
    expect(diagnostics.trace.requestId).toBe('[id:1]')
    expect(diagnostics.trace.failedStep).toBe('[id:1]')
  })

  it('does not mutate the source diagnostics', () => {
    const source = { trace: { apiKey: 'secret', status: 'failed' } }
    createRedactedDiagnosticBundle(source)

    expect(source).toEqual({ trace: { apiKey: 'secret', status: 'failed' } })
  })

  it.each([
    'ghp_abcdefghijklmnopqrstuvwxyz123456',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signaturevalue',
    '-----BEGIN PRIVATE KEY----- secret material -----END PRIVATE KEY-----',
  ])('fails closed when the final serialized bundle still contains a credential: %s', (secret) => {
    const result = serializeRedactedDiagnosticBundle({
      schemaVersion: 1,
      generatedAt: '2026-08-17T00:00:00.000Z',
      diagnostics: { innocuousLabel: secret },
    })

    expect(result).toEqual({ ok: false, reason: 'diagnostic_secret_scan_failed' })
  })

  it('serializes a sanitized bundle only after the final leak scan passes', () => {
    const result = serializeRedactedDiagnosticBundle(createRedactedDiagnosticBundle({ trace: { status: 'failed' } }))

    expect(result.ok).toBe(true)
    if (result.ok) expect(result.json).toContain('"schemaVersion": 1')
  })
})

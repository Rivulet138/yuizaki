import { describe, expect, it } from 'vitest'
import { createHash } from 'node:crypto'

import {
  ProtocolLedger,
  matchProtocolPayload,
  runtimeProtocolHash,
  runtimeProtocolManifest,
} from '../../shared/runtimeProtocol'

describe('runtime protocol manifest', () => {
  it('has exactly the four authority sections and one stable hash', () => {
    expect(Object.keys(runtimeProtocolManifest)).toEqual([
      'production_protocol',
      'fixture_variants',
      'e2e_controls',
      'cases',
    ])
    expect(runtimeProtocolHash).toMatch(/^[a-f0-9]{64}$/)
    const canonicalManifest = JSON.stringify(runtimeProtocolManifest)
    expect(runtimeProtocolHash).toBe(createHash('sha256').update(canonicalManifest).digest('hex'))
  })

  it('matches required, optional, absent, nullable, and oneOf payload fields', () => {
    const schema = runtimeProtocolManifest.production_protocol.event_schemas['tts:done']

    expect(matchProtocolPayload(schema, {
      session_id: 's1',
      generation_id: 'g1',
      turn_id: 't1',
      request_id: 'r1',
      interruption_epoch: 0,
      version: 1,
      sequence: 1,
      is_final: true,
      complete: true,
    }).ok).toBe(true)
    expect(matchProtocolPayload(schema, {
      session_id: 's1',
      generation_id: 'g1',
      turn_id: 't1',
      request_id: 'r1',
      interruption_epoch: 0,
      version: 1,
      sequence: 1,
      is_final: true,
      audio_url: 'http://127.0.0.1/audio.wav',
      text: 'done',
    }).ok).toBe(true)
    expect(matchProtocolPayload(schema, {
      session_id: 's1',
      generation_id: 'g1',
      turn_id: 't1',
      request_id: 'r1',
      interruption_epoch: 0,
      version: 1,
      sequence: 1,
      is_final: true,
      complete: null,
    }).ok).toBe(false)
    expect(matchProtocolPayload(schema, { is_final: true }).ok).toBe(false)
  })

  it('records exact case counts/order and rejects unlisted interactions', () => {
    const ledger = new ProtocolLedger('E2E-08')
    ledger.record({ channel: 'http', direction: 'supervisor->fixture', name: 'GET /api/ping' })
    ledger.record({ channel: 'http', direction: 'supervisor->fixture', name: 'POST /__e2e__/case/start' })
    ledger.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    ledger.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    ledger.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    ledger.record({ channel: 'http', direction: 'main->fixture', name: 'POST /api/system/onboarding/readiness/run' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/settings/' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/workspaces' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'POST /api/system/active-workspace' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/sessions?scope=all' })
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'connect' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/ping' })
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'PATCH /api/workspaces/default' })
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'disconnect' })
    ledger.record({ channel: 'http', direction: 'main->fixture', name: 'POST /__e2e__/case/assert' })

    expect(ledger.assertComplete()).toEqual({ ok: true, missing: [], unexpected: [] })

    const unexpected = new ProtocolLedger('E2E-08')
    unexpected.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/unlisted' })
    expect(unexpected.assertComplete().unexpected).toContain('http renderer->fixture GET /api/unlisted')
  })

  it('supports ordered repeated route expectations', () => {
    const ledger = new ProtocolLedger('E2E-05')
    const record = (name: string, direction: 'supervisor->fixture' | 'main->fixture' | 'renderer->fixture') => (
      ledger.record({ channel: 'http', direction, name })
    )
    record('GET /api/ping', 'supervisor->fixture')
    record('POST /__e2e__/case/start', 'supervisor->fixture')
    record('GET /api/ping', 'main->fixture')
    record('GET /api/ping', 'main->fixture')
    record('GET /api/ping', 'main->fixture')
    record('POST /api/system/onboarding/readiness/run', 'main->fixture')
    record('GET /api/settings/', 'renderer->fixture')
    record('GET /api/workspaces', 'renderer->fixture')
    record('POST /api/system/active-workspace', 'renderer->fixture')
    record('GET /api/sessions?scope=all', 'renderer->fixture')
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'connect' })
    record('GET /api/ping', 'renderer->fixture')
    record('POST /__e2e__/proactive-event', 'main->fixture')
    record('GET /api/system/companion-runtime?limit=8', 'renderer->fixture')
    record('GET /api/system/proactive/settings', 'renderer->fixture')
    record('GET /api/system/proactive/settings', 'renderer->fixture')
    record('GET /api/system/activity-frames', 'renderer->fixture')
    record('GET /api/system/activity-frames', 'renderer->fixture')
    record('POST /api/system/companion-runtime/opportunities/outcome/proactive-job-A', 'renderer->fixture')
    record('POST /__e2e__/proactive-event', 'main->fixture')
    record('GET /api/system/companion-runtime?limit=8', 'renderer->fixture')
    record('POST /__e2e__/proactive-event', 'main->fixture')
    record('GET /api/system/companion-runtime?limit=8', 'renderer->fixture')
    record('GET /api/system/proactive/settings', 'renderer->fixture')
    record('GET /api/system/activity-frames', 'renderer->fixture')
    record('POST /api/system/companion-runtime/opportunities/outcome/proactive-job-B', 'renderer->fixture')
    record('POST /__e2e__/proactive-event', 'main->fixture')
    record('GET /api/system/companion-runtime?limit=8', 'renderer->fixture')
    record('GET /api/system/proactive/settings', 'renderer->fixture')
    record('GET /api/system/proactive/settings', 'renderer->fixture')
    record('GET /api/system/activity-frames', 'renderer->fixture')
    record('GET /api/system/activity-frames', 'renderer->fixture')
    record('POST /api/system/companion-runtime/opportunities/outcome/proactive-job-C', 'renderer->fixture')
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'disconnect' })
    record('POST /__e2e__/case/assert', 'main->fixture')
    expect(ledger.assertComplete()).toEqual({ ok: true, missing: [], unexpected: [] })
  })

  it('rejects llm delta arriving after final', () => {
    const ledger = new ProtocolLedger('E2E-01')
    ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'llm:final' })
    ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'llm:delta' })

    expect(ledger.assertComplete().missing).toContain(
      'socket fixture->renderer llm:delta expected 1..1',
    )
  })

  it('rejects permission requests arriving after their responses', () => {
    const ledger = new ProtocolLedger('E2E-03')
    for (let index = 0; index < 2; index += 1) {
      ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'permission:response' })
      ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'permission:request' })
    }

    expect(ledger.assertComplete().unexpected).toContain(
      'socket fixture->renderer permission:request out of order',
    )
  })

  it('rejects heartbeat response before heartbeat request', () => {
    const ledger = new ProtocolLedger('E2E-05T')
    ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'heartbeat' })
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'heartbeat' })

    expect(ledger.assertComplete().unexpected).toContain(
      'socket renderer->fixture heartbeat out of order',
    )
  })

  it('allows interactions in the same order group in either arrival order', () => {
    const ledger = new ProtocolLedger('E2E-02')
    ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'tts:chunk' })
    ledger.record({ channel: 'socket', direction: 'fixture->renderer', name: 'llm:final' })

    expect(ledger.assertComplete().unexpected).toEqual([])
  })

  it('allows onboarding readiness to race renderer bootstrap', () => {
    const rendererFirst = new ProtocolLedger('E2E-01')
    rendererFirst.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/settings/' })
    rendererFirst.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    rendererFirst.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    rendererFirst.record({ channel: 'http', direction: 'main->fixture', name: 'POST /api/system/onboarding/readiness/run' })

    const readinessFirst = new ProtocolLedger('E2E-01')
    readinessFirst.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    readinessFirst.record({ channel: 'http', direction: 'main->fixture', name: 'GET /api/ping' })
    readinessFirst.record({ channel: 'http', direction: 'main->fixture', name: 'POST /api/system/onboarding/readiness/run' })
    readinessFirst.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/settings/' })

    expect(rendererFirst.assertComplete().unexpected).toEqual([])
    expect(readinessFirst.assertComplete().unexpected).toEqual([])
  })

  it('applies ordering to optional interactions when they occur', () => {
    const ledger = new ProtocolLedger('E2E-01')
    ledger.record({ channel: 'http', direction: 'renderer->fixture', name: 'GET /api/system/permissions' })
    ledger.record({ channel: 'socket', direction: 'renderer->fixture', name: 'connect' })

    expect(ledger.assertComplete().unexpected).toContain(
      'socket renderer->fixture connect out of order',
    )
  })
})

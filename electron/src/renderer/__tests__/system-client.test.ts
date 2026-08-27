import { afterEach, describe, expect, it, vi } from 'vitest'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { systemClient } from '../api/clients/system-client'

describe('systemClient exports', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('downloads database exports through the control server', async () => {
    const exportBlob = new Blob(['session_id,total\n'], { type: 'text/csv' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(exportBlob),
    }))

    const blob = await systemClient.exportData('csv')

    expect(blob).toBe(exportBlob)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/export/csv`, expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('toggles agent plugins through the control server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, plugin: null }),
    }))

    const result = await systemClient.toggleAgentPlugin('memory-router', false)

    expect(result).toEqual({ ok: true, plugin: null })
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/agent-plugins/memory-router/toggle`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: false }),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('loads bounded experience metrics through the control server', async () => {
    const payload = { window: { generation_samples: 4 }, latency: {} }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const result = await systemClient.experienceMetrics()

    expect(result).toBe(payload)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/experience-metrics`, expect.any(Object))
  })

  it('loads the unified provider registry through the control server', async () => {
    const payload = { schemaVersion: 1, providers: [], summary: {} }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const result = await systemClient.providers()

    expect(result).toBe(payload)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/providers`, expect.any(Object))
  })

  it('loads the unified connector registry through the control server', async () => {
    const payload = {
      schemaVersion: 1,
      connectors: [{ id: 'telegram', state: 'uninstalled' }],
      summary: { total: 1, installed: 0, enabled: 0, running: 0, failures: 0, uninstalled: 1, canDisable: 0 },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const result = await systemClient.connectors()

    expect(result).toBe(payload)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/connectors`, expect.any(Object))
  })

  it('loads the evidence-backed platform matrix through the control server', async () => {
    const payload = { schemaVersion: 1, host: { system: 'windows', release: 'test', displayServer: 'unknown' }, platforms: [], statusLegend: [] }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    expect(await systemClient.platforms()).toBe(payload)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/platforms`, expect.any(Object))
  })

  it('normalizes connector delivery telemetry and retries the persisted reply', async () => {
    const raw = {
      delivery_key: 'connector:qq:event-1',
      idempotency_key: 'connector:qq:event-1',
      connector_id: 'qq',
      event_id: 'event-1',
      status: 'failed',
      attempt_count: 2,
      last_error: 'timeout',
      updated_at: 100,
      delivered_at: null,
    }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, connector_id: 'qq', items: [raw] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, delivery: { ...raw, status: 'delivered', attempt_count: 3, delivered_at: 101 } }) }))

    const listed = await systemClient.connectorDeliveries('qq')
    expect(listed.items[0]).toEqual(expect.objectContaining({
      deliveryKey: 'connector:qq:event-1',
      eventId: 'event-1',
      attemptCount: 2,
      retryable: true,
    }))
    const retried = await systemClient.retryConnectorDelivery('qq', 'connector:qq:event-1')
    expect(retried.delivery).toEqual(expect.objectContaining({ status: 'delivered', attemptCount: 3, retryable: false }))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/connectors/qq/deliveries/connector%3Aqq%3Aevent-1/retry`, expect.objectContaining({ method: 'POST' }))
  })

  it('projects processing as cancellable and calls event cancellation by provider event id', async () => {
    const raw = {
      delivery_key: 'connector:telegram:event processing',
      idempotency_key: 'connector:telegram:event processing',
      connector_id: 'telegram',
      event_id: 'event processing',
      status: 'processing',
      attempt_count: 0,
      last_error: null,
      updated_at: 0,
      delivered_at: null,
    }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, connector_id: 'telegram', items: [raw] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, cancelled: true, outcome: 'cancelled', status: 'cancelled' }) }))

    const listed = await systemClient.connectorDeliveries('telegram')
    expect(listed.items[0]).toEqual(expect.objectContaining({
      status: 'processing',
      cancellable: true,
      retryable: false,
    }))

    const cancelled = await systemClient.cancelConnectorEvent('telegram', 'event processing')
    expect(cancelled).toEqual(expect.objectContaining({ cancelled: true, outcome: 'cancelled' }))
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/api/system/connectors/telegram/events/event%20processing/cancel`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('encodes connector IDs when disabling a connector', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'connector-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await systemClient.disableConnector('plugin:voice/router alpha')

    expect(fetch).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/connectors/plugin%3Avoice%2Frouter%20alpha/disable`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'x-trace-id': expect.stringMatching(/^trace_/) }),
      }),
    )
  })

  it('reads and updates redacted message connector settings', async () => {
    const snapshot = {
      id: 'telegram',
      enabled: false,
      botTokenConfigured: true,
      webhookSecretConfigured: false,
      publicKeyConfigured: false,
      webhookPath: '/api/system/connectors/telegram/webhook',
    }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue(snapshot) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ ok: true, config: { ...snapshot, enabled: true } }) }))

    expect(await systemClient.connectorConfig('telegram')).toBe(snapshot)
    const updated = await systemClient.updateConnectorConfig('telegram', { enabled: true, webhookSecret: 'new-secret' })

    expect(updated.config.enabled).toBe(true)
    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/connectors/telegram/config`, expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/connectors/telegram/config`, expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ enabled: true, webhookSecret: 'new-secret' }),
      headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
    }))
  })

  it('unbinds a personal bridge through the credential-clearing endpoint', async () => {
    const payload = {
      ok: true,
      account: { connectorId: 'qq', loginState: 'signed_out' },
      config: { id: 'qq', enabled: false, bridgeUrl: '', bridgeProtocol: 'generic', bridgeTokenConfigured: false },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const result = await systemClient.unbindConnectorAccount('qq')

    expect(result).toEqual(payload)
    expect(fetch).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/connectors/qq/account`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('reads and patches product metrics consent through the control server', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ consented: false, scope: 'local_product_metrics', transport: 'not_configured' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ consented: true, scope: 'local_product_metrics', transport: 'not_configured' }),
      }))

    expect((await systemClient.productMetricsConsent()).consented).toBe(false)
    expect((await systemClient.patchProductMetricsConsent(true)).consented).toBe(true)
    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/product-metrics/consent`, expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/product-metrics/consent`, expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ consented: true }),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
      }),
    }))
  })

  it('encodes MCP server names in dynamic control routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'mcp-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await systemClient.toggleMcp('local tools/fetch server', true)
    await systemClient.refreshMcp('local tools/fetch server')
    await systemClient.removeMcp('local tools/fetch server')

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/mcp/local%20tools%2Ffetch%20server/toggle`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: true }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/mcp/local%20tools%2Ffetch%20server/refresh`, expect.objectContaining({
      method: 'POST',
    }))
    expect(fetch).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/api/system/mcp/local%20tools%2Ffetch%20server`, expect.objectContaining({
      method: 'DELETE',
    }))
  })

  it('encodes agent plugin IDs in dynamic control routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'encoded-plugin-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, plugin: null }),
    }))

    await systemClient.toggleAgentPlugin('voice/router alpha', true)
    await systemClient.updateAgentPluginConfig('voice/router alpha', { mode: 'local' })

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/agent-plugins/voice%2Frouter%20alpha/toggle`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: true }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/agent-plugins/voice%2Frouter%20alpha/config`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ mode: 'local' }),
    }))
  })

  it('encodes schedule IDs in dynamic control routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'schedule-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await systemClient.toggleSchedule('daily/tasks review', false)
    await systemClient.runScheduleNow('daily/tasks review')
    await systemClient.cancelSchedule('daily/tasks review')
    await systemClient.removeSchedule('daily/tasks review')

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review/toggle`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: false }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review/run`, expect.objectContaining({
      method: 'POST',
    }))
    expect(fetch).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review/cancel`, expect.objectContaining({
      method: 'POST',
    }))
    expect(fetch).toHaveBeenNthCalledWith(4, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review`, expect.objectContaining({
      method: 'DELETE',
    }))
  })

  it('writes a proactive outcome to the correlated heartbeat job', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'heartbeat-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await systemClient.resolveCompanionOpportunity('heartbeat/job 1', {
      request_id: 'heartbeat-request-1',
      outcome: 'suppressed',
      reason: 'dnd',
    })

    expect(fetch).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/companion-runtime/opportunities/outcome/heartbeat%2Fjob%201`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ request_id: 'heartbeat-request-1', outcome: 'suppressed', reason: 'dnd' }),
      }),
    )
  })

  it('saves agent plugin config through the control server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, plugin: null }),
    }))

    const config = { mode: 'strict', limit: 3 }
    const result = await systemClient.updateAgentPluginConfig('memory-router', config)

    expect(result).toEqual({ ok: true, plugin: null })
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/agent-plugins/memory-router/config`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(config),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('previews backup restores through the control server by default', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        ok: true,
        dryRun: true,
        backupDir: 'E:/yuizaki/backups/backup-test',
        restorePlan: [],
      }),
    }))

    const result = await systemClient.restoreBackup('E:/yuizaki/backups/backup-test')

    expect(result.dryRun).toBe(true)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/backup/restore`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ backupDir: 'E:/yuizaki/backups/backup-test', dryRun: true }),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })
})

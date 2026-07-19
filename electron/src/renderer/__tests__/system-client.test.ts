import { afterEach, describe, expect, it, vi } from 'vitest'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { systemClient } from '../api/clients/system-client'

describe('systemClient exports', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('downloads database exports through the authenticated control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'export-token')
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
        Authorization: 'Bearer export-token',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('toggles agent plugins through the authenticated control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'agent-plugin-token')
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
        Authorization: 'Bearer agent-plugin-token',
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('loads bounded experience metrics through the authenticated control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'metrics-token')
    const payload = { window: { generation_samples: 4 }, latency: {} }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const result = await systemClient.experienceMetrics()

    expect(result).toBe(payload)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/experience-metrics`, expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer metrics-token' }),
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
    await systemClient.removeSchedule('daily/tasks review')

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review/toggle`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ enabled: false }),
    }))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review/run`, expect.objectContaining({
      method: 'POST',
    }))
    expect(fetch).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/api/system/schedules/daily%2Ftasks%20review`, expect.objectContaining({
      method: 'DELETE',
    }))
  })

  it('saves agent plugin config through the authenticated control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'agent-plugin-config-token')
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
        Authorization: 'Bearer agent-plugin-config-token',
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('previews backup restores through the authenticated control server by default', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'restore-token')
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
        Authorization: 'Bearer restore-token',
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })
})

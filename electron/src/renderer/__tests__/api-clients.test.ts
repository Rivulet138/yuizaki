import { afterEach, describe, expect, it, vi } from 'vitest'
import { pluginClient } from '../api/clients/plugin-client'
import { workspaceClient } from '../api/clients/workspace-client'
import { resourceClient } from '../api/clients/resource-client'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'

describe('api clients', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('encodes workspace IDs in dynamic control routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'workspace-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ id: '桌宠/workspace alpha' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await workspaceClient.update('桌宠/workspace alpha', { name: '日常工作区' })
    await workspaceClient.remove('桌宠/workspace alpha')

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/workspaces/%E6%A1%8C%E5%AE%A0%2Fworkspace%20alpha`, expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ name: '日常工作区' }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/workspaces/%E6%A1%8C%E5%AE%A0%2Fworkspace%20alpha`, expect.objectContaining({
      method: 'DELETE',
    }))
  })

  it('encodes plugin execution cancellation routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'plugin-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, invocationId: 'run 1', status: 'cancelled' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await pluginClient.cancelExecution('voice/tools', 'route alpha/stop', 'run/1')

    expect(fetchMock).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/plugin/voice%2Ftools/route%20alpha%2Fstop?runId=run%2F1`, expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({ Authorization: 'Bearer plugin-token' }),
    }))
  })

  it('maps the streaming Sherpa install button to its dedicated route', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'resource-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ success: true, status: {} }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await resourceClient.prepareSherpaOnline()

    expect(fetchMock).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/resources/sherpa-online/download`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('sends permanent storage cleanup through the unified backend route', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'storage-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ deleted_files: 1, status: {} }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await resourceClient.cleanupStorage(['tts_audio', 'memory'])

    expect(fetchMock).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/storage/cleanup`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          targets: ['tts_audio', 'memory'],
          confirmation: 'PERMANENT_CLEAN',
        }),
      }),
    )
  })
})

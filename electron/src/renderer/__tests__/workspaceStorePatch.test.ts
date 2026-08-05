import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CONTROL_ORIGIN } from '../api/clients/http-client'
import { useWorkspaceStore } from '../stores/workspaceStore'


describe('workspaceStore partial patch compatibility', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([{
      id: 'default',
      name: 'Default',
      description: 'before',
      companion_profile_id: 'companion-1',
      default_model: 'model-1',
      tool_preset: '["clock"]',
      memory_scope: 'workspace',
      mcp_preset_id: 'browser',
      createdAt: '2026-01-01T00:00:00.000Z',
      updatedAt: '2026-01-01T00:00:00.000Z',
      context: { activeTab: 'chat', futureBackendField: { preserve: true } },
    }]))
  })

  it('preserves omitted fields and context while sending only the explicit patch', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: 'default',
        name: 'Default',
        description: 'after',
        updated_at: '2026-02-01T00:00:00.000Z',
      }),
    }))
    const store = useWorkspaceStore()

    await store.updateWorkspaceRemote('default', { description: 'after' })

    expect(store.activeWorkspace).toMatchObject({
      description: 'after',
      companion_profile_id: 'companion-1',
      default_model: 'model-1',
      tool_preset: '["clock"]',
      memory_scope: 'workspace',
      mcp_preset_id: 'browser',
      context: { futureBackendField: { preserve: true } },
    })
    expect(fetch).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/workspaces/default`,
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ description: 'after' }),
      }),
    )
  })
})

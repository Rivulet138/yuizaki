import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkspaceStore } from '../stores/workspaceStore'
import { clearControlAuthToken, CONTROL_ORIGIN } from '../api/clients/http-client'

describe('workspaceStore active workspace switching', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([
      {
        id: 'default',
        name: 'Default',
        createdAt: '',
        updatedAt: '',
        context: { activeTab: 'companion', modelType: 'live2d', modelId: 'hiyori', wallpaperMode: true, heroHeight: 460, menuOrder: [], recentTabs: [], layoutPreset: 'balanced' },
      },
      {
        id: 'ws-2',
        name: 'Focus',
        createdAt: '',
        updatedAt: '',
        context: { activeTab: 'chat', modelType: 'live2d', modelId: 'hiyori', wallpaperMode: true, heroHeight: 460, menuOrder: [], recentTabs: [], layoutPreset: 'balanced' },
      },
    ]))
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ ok: true, workspace_id: 'ws-2' }),
      }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
  })

  it('persists active workspace changes and promotes recent workspace order', async () => {
    const store = useWorkspaceStore()

    store.setActiveWorkspace('ws-2')

    expect(store.activeWorkspaceId).toBe('ws-2')
    expect(store.activeWorkspace.id).toBe('ws-2')
    expect(store.recentWorkspaceIds[0]).toBe('ws-2')
    expect(store.activeWorkspace.context.promptMode).toBe('auto')
    expect(store.activeWorkspace.context.promptVersion).toBe(2)
    expect(store.activeWorkspace.context.promptEngineering.workPrompt).toContain('任务协助模式')
    expect(store.activeWorkspace.context.promptEngineering.workPrompt).toContain('工具结果')
    expect(store.activeWorkspace.context.promptEngineering.dailyPrompt).toContain('日常陪伴模式')
    expect(store.activeWorkspace.context.promptEngineering.dailyPrompt).toContain('实时画面')
    expect(store.activeWorkspace.context.roleCard).toMatchObject({ enabled: true })
    expect(store.activeWorkspace.context.worldBook).toMatchObject({ enabled: false, entries: [] })
    expect(store.activeWorkspace.context.vision).toEqual({
      enabled: true,
      displayIndex: 0,
      intervalMs: 2000,
      pauseWhenAppHidden: true,
      captureMode: 'display',
      region: { x: 0, y: 0, width: 1280, height: 720 },
      privacyMasks: [],
    })
    expect(store.activeWorkspace.context.memoryPolicy).toEqual({
      workingRetentionDays: 14,
      lowQualityThreshold: 0.55,
      includeStaleWorking: true,
      includeLowQuality: true,
      includeExactDuplicates: true,
    })
    expect(window.localStorage.getItem('deskpet-active-workspace')).toBe('ws-2')
    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        `${CONTROL_ORIGIN}/api/system/active-workspace`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ workspace_id: 'ws-2' }),
          headers: expect.objectContaining({
            Authorization: 'Bearer backend-token',
          }),
        }),
      )
    })
  })

  it('can wait for the backend active workspace sync before continuing', async () => {
    const store = useWorkspaceStore()

    await store.setActiveWorkspaceSynced('ws-2')

    expect(store.activeWorkspaceId).toBe('ws-2')
    expect(fetch).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/api/system/active-workspace`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ workspace_id: 'ws-2' }),
      }),
    )
  })

  it('normalizes realtime vision region settings into safe capture bounds', () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([{
      id: 'default',
      name: 'Default',
      createdAt: '',
      updatedAt: '',
      context: {
        activeTab: 'companion',
        modelType: 'live2d',
        vision: {
          enabled: true,
          displayIndex: 1,
          intervalMs: 2000,
          pauseWhenAppHidden: true,
          captureMode: 'region',
          region: { x: -20, y: 40, width: 10, height: 800 },
          privacyMasks: [
            { x: -10, y: 20, width: 12, height: 18 },
            { x: 100, y: 200, width: 300, height: 400 },
          ],
        },
      },
    }]))

    const store = useWorkspaceStore()

    expect(store.activeWorkspace.context.vision).toEqual({
      enabled: true,
      displayIndex: 1,
      intervalMs: 2000,
      pauseWhenAppHidden: true,
      captureMode: 'region',
      region: { x: 0, y: 40, width: 64, height: 800 },
      privacyMasks: [
        { x: 0, y: 20, width: 64, height: 64 },
        { x: 100, y: 200, width: 300, height: 400 },
      ],
    })
  })

  it('migrates only the legacy default workspace label to desktop pet scene wording', () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([
      {
        id: 'default',
        name: '默认工作区',
        createdAt: '',
        updatedAt: '',
        context: {},
      },
      {
        id: 'custom',
        name: '我的工作区',
        createdAt: '',
        updatedAt: '',
        context: {},
      },
    ]))

    const store = useWorkspaceStore()

    expect(store.workspaces.find((workspace) => workspace.id === 'default')?.name).toBe('默认场景')
    expect(store.workspaces.find((workspace) => workspace.id === 'custom')?.name).toBe('我的工作区')
  })
})

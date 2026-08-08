import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '../stores/sessionStore'
import { clearControlAuthToken } from '../api/clients/http-client'

const jsonResponse = (payload: unknown) => ({
  ok: true,
  status: 200,
  json: vi.fn().mockResolvedValue(payload),
})

describe('sessionStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
    window.sessionStorage.setItem('yuizaki.control.token', 'session-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('keeps session state stable when the control server returns a malformed list payload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ ok: true })))

    const store = useSessionStore()

    await store.loadSessions()

    expect(store.sessions).toEqual([])
    expect(store.activeSessionId).toBe('default')
  })

  it('loads all sessions and keeps the active session inside the current workspace', async () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([
      {
        id: 'team/alpha',
        name: 'Team Alpha',
        createdAt: '',
        updatedAt: '',
        context: { activeTab: 'chat', modelType: 'live2d', modelId: null, wallpaperMode: true, heroHeight: 460, menuOrder: [], recentTabs: [], layoutPreset: 'balanced' },
      },
    ]))
    window.localStorage.setItem('deskpet-active-workspace', 'team/alpha')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      sessions: [
        {
          id: 'other-session',
          workspace_id: 'team/beta',
          title: 'Other',
          pinned: false,
          created_at: null,
          updated_at: null,
          message_count: 0,
          total_tokens: 0,
        },
        {
          id: 'team-session',
          workspace_id: 'team/alpha',
          title: 'Team',
          pinned: false,
          created_at: null,
          updated_at: null,
          message_count: 1,
          total_tokens: 0,
        },
      ],
    })))

    const store = useSessionStore()
    store.setActiveSession('other-session')

    await store.loadSessions()

    expect(fetch).toHaveBeenCalledWith('http://localhost:38945/api/sessions?scope=all', expect.any(Object))
    expect(store.sessions.map((session) => session.id)).toEqual(['other-session', 'team-session'])
    expect(store.activeSessionId).toBe('team-session')
  })

  it('encodes workspace and session ids before calling session APIs', async () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([
      {
        id: 'team/alpha',
        name: 'Team Alpha',
        createdAt: '',
        updatedAt: '',
        context: { activeTab: 'chat', modelType: 'live2d', modelId: null, wallpaperMode: true, heroHeight: 460, menuOrder: [], recentTabs: [], layoutPreset: 'balanced' },
      },
    ]))
    window.localStorage.setItem('deskpet-active-workspace', 'team/alpha')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ sessions: [] }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'folder/session 1',
        workspace_id: 'team/alpha',
        title: 'New',
        pinned: false,
        created_at: null,
        updated_at: null,
        message_count: 0,
        total_tokens: 0,
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'folder/session 1',
        workspace_id: 'team/alpha',
        title: 'Renamed',
        pinned: false,
        created_at: null,
        updated_at: null,
        message_count: 0,
        total_tokens: 0,
      }))
      .mockResolvedValueOnce(jsonResponse({ status: 'deleted' }))
    vi.stubGlobal('fetch', fetchMock)

    const store = useSessionStore()

    await store.loadSessions()
    await store.createSession('New')
    await store.updateSession('folder/session 1', { title: 'Renamed' }, 'team/alpha')
    await store.deleteSession('folder/session 1', 'team/alpha')

    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:38945/api/sessions?scope=all')
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:38945/api/workspaces/team%2Falpha/sessions')
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:38945/api/sessions/folder%2Fsession%201?workspace_id=team%2Falpha')
    expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:38945/api/sessions/folder%2Fsession%201?workspace_id=team%2Falpha')
  })

  it('creates a non-destructive branch through the dedicated endpoint', async () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([{
      id: 'team/alpha',
      name: 'Team Alpha',
      createdAt: '',
      updatedAt: '',
      context: { activeTab: 'chat', modelType: 'live2d', modelId: null, wallpaperMode: true, heroHeight: 460, menuOrder: [], recentTabs: [], layoutPreset: 'balanced' },
    }]))
    window.localStorage.setItem('deskpet-active-workspace', 'team/alpha')
    const branch = {
      id: 'branch-1',
      workspace_id: 'team/alpha',
      title: 'Branch',
      summary: null,
      pinned: false,
      archived: false,
      parent_session_id: 'source/session',
      branched_from_message_id: 42,
      created_at: null,
      updated_at: null,
      message_count: 2,
      total_tokens: 8,
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(branch))
    vi.stubGlobal('fetch', fetchMock)
    const store = useSessionStore()

    const created = await store.branchSession('source/session', 42, 'Branch', 'team/alpha')

    expect(created).toEqual(branch)
    expect(store.sessions[0]).toEqual(branch)
    expect(store.activeSessionId).toBe('branch-1')
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:38945/api/session-branches', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        source_session_id: 'source/session',
        message_id: 42,
        title: 'Branch',
        workspace_id: 'team/alpha',
      }),
    }))
  })
})

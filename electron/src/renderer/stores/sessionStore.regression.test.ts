import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore, type SessionRecord } from './sessionStore'

const mocks = vi.hoisted(() => ({ request: vi.fn(), workspace: {} as { activeWorkspace: { id: string } | null } }))
vi.mock('@/api/clients/http-client', () => ({ requestJson: mocks.request, CONTROL_ORIGIN: 'http://control.test' }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => mocks.workspace }))

const session = (id: string, workspace_id: string): SessionRecord => ({
  id, workspace_id, title: id, pinned: false, created_at: null, updated_at: null, message_count: 0, total_tokens: 0,
})
const deferred = () => {
  let resolve!: (payload: { sessions: SessionRecord[] }) => void
  const promise = new Promise<{ sessions: SessionRecord[] }>(done => { resolve = done })
  return { promise, resolve }
}

describe('session list request ownership', () => {
  let pinia: ReturnType<typeof createPinia>
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.workspace = reactive({ activeWorkspace: { id: 'A' } })
    pinia = createPinia()
    setActivePinia(pinia)
  })
  afterEach(() => { disposePinia(pinia) })

  it('keeps fast workspace B results when slow workspace A returns later', async () => {
    const slow = deferred()
    const fast = deferred()
    mocks.request.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise)
    const store = useSessionStore()
    const loadingA = store.loadSessions()
    mocks.workspace.activeWorkspace = { id: 'B' }
    const loadingB = store.loadSessions()
    fast.resolve({ sessions: [session('b', 'B')] })
    await loadingB
    expect(store.activeSessionId).toBe('b')
    expect(store.loading).toBe(false)
    slow.resolve({ sessions: [session('a', 'A')] })
    await loadingA
    expect(store.sessions).toEqual([session('b', 'B')])
    expect(store.activeSessionId).toBe('b')
    expect(store.loading).toBe(false)
  })

  it('does not let an obsolete completion clear the latest loading flag', async () => {
    const first = deferred()
    const second = deferred()
    mocks.request.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const store = useSessionStore()
    const oldLoad = store.loadSessions()
    const newLoad = store.loadSessions()
    first.resolve({ sessions: [session('old', 'A')] })
    await oldLoad
    expect(store.loading).toBe(true)
    expect(store.sessions).toEqual([])
    second.resolve({ sessions: [session('new', 'A')] })
    await newLoad
    expect(store.activeSessionId).toBe('new')
    expect(store.loading).toBe(false)
  })

  it('discards a response after switching workspaces even without another load', async () => {
    const pending = deferred()
    mocks.request.mockReturnValueOnce(pending.promise)
    const store = useSessionStore()
    store.sessions = [session('b', 'B')]
    const loading = store.loadSessions()
    mocks.workspace.activeWorkspace = { id: 'B' }
    store.setActiveSession('b')
    pending.resolve({ sessions: [session('a', 'A')] })
    await loading
    expect(store.sessions).toEqual([session('b', 'B')])
    expect(store.activeSessionId).toBe('b')
    expect(store.loading).toBe(false)
  })

  it('keeps a newer request authoritative through an A/B/A workspace round trip', async () => {
    const old = deferred()
    const current = deferred()
    mocks.request.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const store = useSessionStore()
    const oldLoad = store.loadSessions()
    mocks.workspace.activeWorkspace = { id: 'B' }
    mocks.workspace.activeWorkspace = { id: 'A' }
    const newLoad = store.loadSessions()
    current.resolve({ sessions: [session('new', 'A')] })
    await newLoad
    old.resolve({ sessions: [session('old', 'A')] })
    await oldLoad
    expect(store.activeSessionId).toBe('new')
    expect(store.sessions.map(item => item.id)).toEqual(['new'])
  })

  it('invalidates the old load on an A/B/A round trip without starting a new load', async () => {
    const pending = deferred()
    mocks.request.mockReturnValueOnce(pending.promise)
    const store = useSessionStore()
    const loading = store.loadSessions()
    mocks.workspace.activeWorkspace = { id: 'B' }
    mocks.workspace.activeWorkspace = { id: 'A' }
    store.sessions = [session('selected', 'A')]
    store.setActiveSession('selected')
    pending.resolve({ sessions: [session('old', 'A')] })
    await loading
    expect(store.activeSessionId).toBe('selected')
    expect(store.sessions.map(item => item.id)).toEqual(['selected'])
    expect(store.loading).toBe(false)
  })

  it('retains a newer explicit selection in the current workspace', async () => {
    const pending = deferred()
    mocks.request.mockReturnValueOnce(pending.promise)
    const store = useSessionStore()
    const loading = store.loadSessions()
    store.setActiveSession('selected')
    pending.resolve({ sessions: [session('first', 'A'), session('selected', 'A')] })
    await loading
    expect(store.activeSessionId).toBe('selected')
  })

  it('finishes loading when no workspace is active', async () => {
    mocks.workspace.activeWorkspace = null
    const store = useSessionStore()
    await store.loadSessions()
    expect(store.loading).toBe(false)
    expect(mocks.request).not.toHaveBeenCalled()
  })
})


describe('session persona override transport', () => {
  let pinia: ReturnType<typeof createPinia>
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.workspace = reactive({ activeWorkspace: { id: 'A' } })
    pinia = createPinia(); setActivePinia(pinia)
  })
  afterEach(() => { disposePinia(pinia) })

  it('sends explicit empty fields and null through the workspace-scoped session PATCH', async () => {
    const store = useSessionStore()
    store.sessions = [session('a', 'A'), session('b', 'B')]
    mocks.request.mockResolvedValueOnce({ ...session('a', 'A'), persona_overrides: { scenario: '' } })
    await store.updateSession('a', { persona_overrides: { scenario: '' } }, 'A')
    expect(mocks.request).toHaveBeenCalledWith('http://control.test/api/sessions/a?workspace_id=A', expect.objectContaining({
      method: 'PATCH', body: JSON.stringify({ persona_overrides: { scenario: '' } }),
    }))
    expect(store.sessions[0]?.persona_overrides).toEqual({ scenario: '' })
    expect(store.sessions[1]).toEqual(session('b', 'B'))
    mocks.request.mockResolvedValueOnce({ ...session('a', 'A'), persona_overrides: null })
    await store.updateSession('a', { persona_overrides: null }, 'A')
    expect(mocks.request).toHaveBeenLastCalledWith('http://control.test/api/sessions/a?workspace_id=A', expect.objectContaining({
      body: JSON.stringify({ persona_overrides: null }),
    }))
    expect(store.sessions[0]?.persona_overrides).toBeNull()
  })
})


describe('session branch creation ownership', () => {
  let pinia: ReturnType<typeof createPinia>
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.workspace = reactive({ activeWorkspace: { id: 'A' } })
    pinia = createPinia()
    setActivePinia(pinia)
  })
  afterEach(() => { disposePinia(pinia) })

  it.each(['default', 'source', 'newer'])('creates a branch without implicitly changing selection %s', async (selectedId) => {
    let resolve!: (value: SessionRecord) => void
    mocks.request.mockReturnValueOnce(new Promise<SessionRecord>(done => { resolve = done }))
    const store = useSessionStore()
    store.sessions = [session('source', 'A'), session('newer', 'B')]
    store.setActiveSession('source')
    const creating = store.branchSession('source', 42, 'Branch', 'A')
    store.setActiveSession(selectedId)
    if (selectedId === 'newer') mocks.workspace.activeWorkspace = { id: 'B' }
    resolve(session('branch', ' A '))
    const branch = await creating
    expect(store.activeSessionId).toBe(selectedId)
    expect(branch).toEqual(session('branch', 'A'))
    expect(store.sessions[0]).toEqual(branch)
    expect(mocks.request).toHaveBeenCalledWith('http://control.test/api/session-branches', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ source_session_id: 'source', message_id: 42, title: 'Branch', workspace_id: 'A' }),
    }))
  })
})

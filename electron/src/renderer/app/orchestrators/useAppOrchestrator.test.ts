import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { useAppOrchestrator } from './useAppOrchestrator'

const mocks = vi.hoisted(() => ({
  workspace: {} as Record<string, unknown>, session: {} as Record<string, unknown>, chat: {} as Record<string, unknown>,
  syncFromBackend: vi.fn(), activate: vi.fn(), loadSessions: vi.fn(), loadHistory: vi.fn(),
  initChatStore: vi.fn(), setWorkspaceContext: vi.fn(), loadCompanions: vi.fn(), setActiveCompanion: vi.fn(),
  applyRuntime: vi.fn(), setModelSelection: vi.fn(), warn: vi.fn(),
}))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => mocks.workspace }))
vi.mock('@/stores/sessionStore', () => ({ useSessionStore: () => mocks.session }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => mocks.chat }))
vi.mock('@/stores/companionStore', () => ({ useCompanionStore: () => ({
  loadCompanions: mocks.loadCompanions, setActiveCompanion: mocks.setActiveCompanion,
}) }))
vi.mock('../composables/useCompanionRuntimeBridge', () => ({ useCompanionRuntimeBridge: () => ({
  applyActiveCompanionRuntime: mocks.applyRuntime, handleCompanionChange: vi.fn(),
}) }))
vi.mock('@/api/client', () => ({ petControlClient: { setModelSelection: mocks.setModelSelection } }))
vi.mock('@/logger', () => ({ logger: { warn: mocks.warn } }))
vi.mock('@/navigation/modules', () => ({ isPanelKey: (key: string) => ['chat', 'settings', 'memory', 'prompt'].includes(key) }))

const renderer = createRenderer<object, object>({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, insert() {}, remove() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})
const deferred = () => {
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  return { promise, resolve }
}
const flush = async () => { await new Promise<void>(resolve => setImmediate(resolve)); await nextTick() }
const workspaces = () => ['default', 'audit-a', 'audit-b'].map(id => ({
  id, context: { activeTab: 'memory', modelId: `${id}-model`, modelType: 'vrm' },
}))

describe('app workspace route ownership', () => {
  let app: ReturnType<typeof renderer.createApp> | undefined
  let router: Router
  let orchestrator: ReturnType<typeof useAppOrchestrator>
  let workspace: { activeWorkspaceId: string; workspaces: ReturnType<typeof workspaces> }
  let session: { activeSessionId: string }
  let chat: { workspaceId: string; sessionId: string }

  beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal('window', { location: { href: 'http://app.test/#/w/audit-a/settings' } })
    vi.stubGlobal('document', { documentElement: { dataset: {} } })
    workspace = reactive({ activeWorkspaceId: 'default', workspaces: workspaces().slice(0, 1) })
    session = reactive({ activeSessionId: 'default' })
    chat = { workspaceId: '', sessionId: '' }
    mocks.workspace = Object.assign(workspace, {
      get activeWorkspace() { return workspace.workspaces.find(item => item.id === workspace.activeWorkspaceId) || workspace.workspaces[0]! },
      syncFromBackend: mocks.syncFromBackend, setActiveWorkspaceSynced: mocks.activate,
    })
    // Keep the store getters reactive when its selected workspace/session changes.
    Object.defineProperty(mocks.workspace, 'activeWorkspace', { get: () => workspace.workspaces.find(item => item.id === workspace.activeWorkspaceId) || workspace.workspaces[0]! })
    mocks.session = session
    Object.assign(mocks.session, { loadSessions: mocks.loadSessions })
    Object.defineProperty(mocks.session, 'activeSession', { configurable: true, get: () => session.activeSessionId === 'default' ? null : { id: session.activeSessionId } })
    mocks.chat = { initChatStore: mocks.initChatStore, loadHistory: mocks.loadHistory, setWorkspaceContext: mocks.setWorkspaceContext }
    mocks.setWorkspaceContext.mockImplementation((workspaceId: string, sessionId: string) => { chat.workspaceId = workspaceId; chat.sessionId = sessionId })
    mocks.syncFromBackend.mockImplementation(async () => { workspace.workspaces = workspaces() })
    mocks.activate.mockImplementation(async (id: string) => {
      if (!workspace.workspaces.some(item => item.id === id)) throw new Error(`Workspace not found: ${id}`)
      workspace.activeWorkspaceId = id
    })
    mocks.loadSessions.mockImplementation(async () => { session.activeSessionId = `${workspace.activeWorkspaceId}-session` })
    mocks.loadCompanions.mockResolvedValue(undefined)
    mocks.applyRuntime.mockResolvedValue(undefined)
    mocks.loadHistory.mockResolvedValue(undefined)
    mocks.setModelSelection.mockResolvedValue(undefined)
    router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/', component: {} },
      { path: '/w/:workspaceId/:tab/:sessionId?', component: {} },
    ] })
  })
  afterEach(() => { app?.unmount(); app = undefined; vi.unstubAllGlobals() })

  const mount = async (path = '/w/audit-a/settings') => {
    await router.push(path)
    app = renderer.createApp({ setup() { orchestrator = useAppOrchestrator(); return () => h('div') } })
    app.use(router)
    app.mount({})
    await flush()
  }

  it('selects a bookmarked workspace after backend discovery before loading its sessions and history', async () => {
    await mount()
    expect(workspace.activeWorkspaceId).toBe('audit-a')
    expect(chat.workspaceId).toBe('audit-a')
    expect(mocks.loadHistory).toHaveBeenCalledWith('audit-a-session', 'audit-a')
    expect(router.currentRoute.value.path).toBe('/w/audit-a/settings')
    expect(document.documentElement.dataset['yuizakiAppReady']).toBe('true')
  })

  it('uses the latest route if navigation changes while backend discovery is pending', async () => {
    const pending = deferred()
    mocks.syncFromBackend.mockImplementationOnce(async () => { await pending.promise; workspace.workspaces = workspaces() })
    await mount()
    await router.push('/w/audit-b/prompt')
    pending.resolve()
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-b')
    expect(mocks.activate).not.toHaveBeenCalledWith('audit-a')
    expect(mocks.loadHistory).toHaveBeenCalledWith('audit-b-session', 'audit-b')
    expect(router.currentRoute.value.path).toBe('/w/audit-b/prompt')
  })

  it('follows SPA navigation and browser back/forward without adding navigation entries', async () => {
    await mount()
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    await router.push('/w/audit-b/memory')
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-b')
    expect(chat.workspaceId).toBe('audit-b')
    await router.push('/w/audit-a/prompt')
    await flush()
    router.back()
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-b')
    expect(router.currentRoute.value.path).toBe('/w/audit-b/memory')
    router.forward()
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-a')
    expect(chat.workspaceId).toBe('audit-a')
    expect(router.currentRoute.value.path).toBe('/w/audit-a/prompt')
    expect(push).toHaveBeenCalledTimes(2)
    expect(replace).not.toHaveBeenCalled()
  })

  it.each(['startup', 'SPA'] as const)('falls back from an unknown workspace during %s', async (mode) => {
    await mount(mode === 'startup' ? '/w/missing/settings' : undefined)
    if (mode === 'SPA') { await router.push('/w/missing/settings'); await flush() }
    expect(router.currentRoute.value.path).toBe('/w/default/chat')
    expect(workspace.activeWorkspaceId).toBe('default')
    expect(chat.workspaceId).toBe('default')
    expect(mocks.activate).not.toHaveBeenCalledWith('missing')
  })

  it('preserves explicit workspace switching, saved tab and pet model restoration', async () => {
    await mount()
    await orchestrator.changeWorkspace('audit-b')
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-b')
    expect(router.currentRoute.value.path).toBe('/w/audit-b/memory/audit-b-session')
    expect(mocks.setModelSelection).toHaveBeenCalledExactlyOnceWith('audit-b-model', 'vrm')
  })

  it.each(['route', 'explicit'] as const)('does not resume an old %s synchronization after selecting another route', async (mode) => {
    await mount('/w/default/settings')
    const pending = deferred()
    mocks.activate.mockImplementationOnce(async (id: string) => { workspace.activeWorkspaceId = id; await pending.promise })
    const switching = mode === 'explicit' ? orchestrator.changeWorkspace('audit-a') : router.push('/w/audit-a/settings')
    await flush()
    await router.push('/w/audit-b/prompt')
    await flush()
    const loads = mocks.loadSessions.mock.calls.length
    pending.resolve()
    await switching
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-b')
    expect(chat.workspaceId).toBe('audit-b')
    expect(mocks.loadSessions).toHaveBeenCalledTimes(loads)
    expect(router.currentRoute.value.path).toBe('/w/audit-b/prompt')
    expect(mocks.setModelSelection).not.toHaveBeenCalled()
  })

  it('invalidates an old synchronization through an A/B/A route round trip', async () => {
    await mount('/w/default/settings')
    const pending = deferred()
    mocks.activate.mockImplementationOnce(async (id: string) => { workspace.activeWorkspaceId = id; await pending.promise })
    await router.push('/w/audit-a/settings')
    await flush()
    await router.push('/w/audit-b/settings')
    await flush()
    await router.push('/w/audit-a/prompt')
    await flush()
    const loads = mocks.loadSessions.mock.calls.length
    pending.resolve()
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-a')
    expect(mocks.loadSessions).toHaveBeenCalledTimes(loads)
    expect(router.currentRoute.value.path).toBe('/w/audit-a/prompt')
  })

  it('does not navigate or restore an old model after a superseded session load', async () => {
    await mount()
    const pending = deferred()
    mocks.loadSessions.mockReturnValueOnce(pending.promise)
    const switching = orchestrator.changeWorkspace('audit-b')
    await flush()
    await router.push('/w/audit-a/prompt')
    await flush()
    pending.resolve()
    await switching
    await flush()
    expect(workspace.activeWorkspaceId).toBe('audit-a')
    expect(router.currentRoute.value.path).toBe('/w/audit-a/prompt')
    expect(mocks.setModelSelection).not.toHaveBeenCalled()
  })

  it('does not resume a pending explicit synchronization after unmount', async () => {
    await mount()
    const push = vi.spyOn(router, 'push')
    const pending = deferred()
    mocks.activate.mockImplementationOnce(async (id: string) => { workspace.activeWorkspaceId = id; await pending.promise })
    const switching = orchestrator.changeWorkspace('audit-b')
    await flush()
    const loads = mocks.loadSessions.mock.calls.length
    app!.unmount(); app = undefined
    pending.resolve()
    await switching
    expect(mocks.loadSessions).toHaveBeenCalledTimes(loads)
    expect(push).not.toHaveBeenCalled()
    expect(mocks.setModelSelection).not.toHaveBeenCalled()
  })

  it('does not navigate after a model restoration is superseded by another route', async () => {
    await mount()
    const pending = deferred()
    mocks.setModelSelection.mockReturnValueOnce(pending.promise)
    const switching = orchestrator.changeWorkspace('audit-b')
    await flush()
    await router.push('/w/audit-a/prompt')
    await flush()
    pending.resolve()
    await switching
    expect(workspace.activeWorkspaceId).toBe('audit-a')
    expect(router.currentRoute.value.path).toBe('/w/audit-a/prompt')
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSSRApp, h, effectScope, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, type EffectScope } from 'vue'
import MemoryPanel from './MemoryPanel.vue'
import { memoryClient } from '@/api/clients/memory-client'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { renderToString } from '@vue/server-renderer'

vi.mock('vue', async original => ({ ...await original<typeof import('vue')>(), useSSRContext: () => ({ modules: new Set() }), provide: vi.fn(), onMounted: vi.fn(), onActivated: vi.fn(), onDeactivated: vi.fn(), onBeforeUnmount: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: vi.fn() }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: vi.fn() }))
vi.mock('@/stores/sessionStore', () => ({ useSessionStore: () => ({ activeSession: { id: 'session-a' } }) }))
vi.mock('@/i18n', () => ({ t: (key: string) => key, currentLocale: { value: 'en' } }))
vi.mock('@/api/clients/memory-client', () => ({ memoryClient: {
  getDocs: vi.fn(), getOverview: vi.fn(), getCandidates: vi.fn(), getOperations: vi.fn(), getIndexStatus: vi.fn(), getIndexRebuildJob: vi.fn(), rebuildIndex: vi.fn(), cancelIndexRebuild: vi.fn(),
} }))
vi.mock('@/api/client', async () => ({ memoryClient: (await import('@/api/clients/memory-client')).memoryClient }))
vi.mock('element-plus', () => ({ ElIcon: {}, ElButton: {}, ElDropdown: {}, ElDropdownItem: {}, ElDropdownMenu: {}, ElSlider: {}, ElOption: {}, ElSelect: {}, ElDialog: {}, ElDrawer: {}, ElForm: {}, ElFormItem: {}, ElInput: {}, ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/dropdown/style/css', () => ({}))
vi.mock('element-plus/es/components/slider/style/css', () => ({}))
vi.mock('element-plus/es/components/select/style/css', () => ({}))
vi.mock('element-plus/es/components/option/style/css', () => ({}))
vi.mock('element-plus/es/components/dialog/style/css', () => ({}))
vi.mock('element-plus/es/components/drawer/style/css', () => ({}))
vi.mock('element-plus/es/components/form/style/css', () => ({}))
vi.mock('element-plus/es/components/form-item/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: { setup: (_props: unknown, { slots }: any) => () => slots.default?.() } }))
vi.mock('../components/MemoryAdvancedTools.vue', () => ({ default: {} }))
vi.mock('../components/MemoryStorageStatus.vue', () => ({ default: {} }))
vi.mock('../components/MemoryLibrary.vue', () => ({ default: { props: ['loading', 'visibleDocs', 'error'], setup: (props: any) => () => h('div', { 'data-testid': 'library-props', 'data-loading': String(props.loading), 'data-error': props.error ?? 'none' }, props.visibleDocs.map((row: any) => h('p', row.text))) } }))
vi.mock('../components/MemoryOverview.vue', () => ({ default: {} }))
vi.mock('../components/MemoryReviewQueue.vue', () => ({ default: {} }))

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const doc = (id: string, text = id) => ({ id, text, metadata: { scope: 'workspace', layer: 'semantic', type: 'fact' } })
const job = (state: string) => ({ job_id: 'job-1', state, phase: 'index', processed_count: state === 'completed' ? 2 : 0, total_count: 2, updated_at: state === 'completed' ? '2026-11-11T01:00:01Z' : '2026-11-11T01:00:00Z' })
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); await nextTick() }
const hook = async (fn: any) => { for (const [callback] of vi.mocked(fn).mock.calls as any[]) callback(); await flush() }
const libraryReads = () => vi.mocked(memoryClient.getDocs).mock.calls.filter(([options]) => options?.includeState !== 'forgotten')
let scope: EffectScope
let state: any
let route: any
let workspace: any
let visibility: EventTarget & { hidden: boolean }

beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers()
  visibility = Object.assign(new EventTarget(), { hidden: false })
  vi.spyOn(visibility, 'removeEventListener')
  vi.stubGlobal('document', visibility)
  vi.stubGlobal('window', { setTimeout, clearTimeout, location: { hash: '#/w/workspace-a/memory' }, localStorage: { getItem: () => null } })
  route = reactive({ name: 'memory', params: { workspaceId: 'workspace-a' }, query: {} as Record<string, unknown> })
  workspace = reactive({ activeWorkspace: { id: 'workspace-a', memory_scope: 'workspace', context: {} } })
  vi.mocked(useRoute).mockReturnValue(route)
  vi.mocked(useWorkspaceStore).mockReturnValue(workspace)
  vi.mocked(memoryClient.getDocs).mockImplementation(async options => ({ docs: options?.includeState === 'forgotten' ? [] : [doc('a'), doc('b')] }))
  vi.mocked(memoryClient.getOverview).mockResolvedValue({ total: 2, by_layer: {}, by_state: {}, by_source: {}, by_review_status: {}, latest_activity: [] } as any)
  vi.mocked(memoryClient.getCandidates).mockResolvedValue({ candidates: [] } as any)
  vi.mocked(memoryClient.getOperations).mockResolvedValue({ operations: [] } as any)
  vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'ok', count: 2 })
  vi.mocked(memoryClient.getIndexRebuildJob).mockResolvedValue({ job: job('running'), index_status: 'rebuilding' } as any)
  scope = effectScope()
  state = scope.run(() => (MemoryPanel as any).setup({}, { expose: vi.fn() }))
})
afterEach(async () => {
  await hook(onBeforeUnmount)
  scope.stop()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
const hidden = async (value: boolean) => { visibility.hidden = value; visibility.dispatchEvent(new Event('visibilitychange')); await flush() }

describe('MemoryPanel cached lifecycle and scoped navigation', () => {
  it('shares the initial mounted/activated refresh', async () => {
    const pending = deferred<any>()
    vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : pending.promise)
    await hook(onMounted)
    await hook(onActivated)
    expect(libraryReads()).toHaveLength(1)
    expect(state.docsRequest.loading).toBe(true)
    pending.resolve({ docs: [doc('a')] })
    await flush()
    expect(memoryClient.getIndexStatus).toHaveBeenCalledTimes(1)
  })
  it('pauses rebuild polling while deactivated and reads the actual terminal state on return', async () => {
    vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
    await hook(onMounted)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(1)
    await hook(onDeactivated)
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(1)
    expect(memoryClient.cancelIndexRebuild).not.toHaveBeenCalled()
    vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'ok', count: 2, job: job('completed') } as any)
    await hook(onActivated)
    expect(state.displayedRebuildJob.value.state).toBe('completed')
    expect(state.rebuildIndexLoading.value).toBe(false)
    expect(libraryReads()).toHaveLength(2)
  })
  it('ignores a poll finishing hidden and resumes one chain across visible/activated events', async () => {
    const pending = deferred<any>()
    vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
    vi.mocked(memoryClient.getIndexRebuildJob).mockReturnValueOnce(pending.promise)
    await hook(onMounted)
    await hidden(true)
    pending.resolve({ job: job('completed'), index_status: 'ok' })
    await flush()
    expect(state.displayedRebuildJob.value.state).toBe('running')
    await vi.advanceTimersByTimeAsync(2000)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(1)
    await hidden(false)
    await hook(onActivated)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(2)
    expect(libraryReads()).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(500)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(3)
    expect(memoryClient.cancelIndexRebuild).not.toHaveBeenCalled()
  })
  it('closes the advanced drawer on deactivation and keeps its query draft on return', async () => {
    await hook(onMounted)
    state.handleAdvancedToolCommand('open-index')
    state.queryForm.query = 'unsaved recall query'
    state.queryForm.top_k = 12
    expect(state.advancedToolsVisible.value).toBe(true)

    await hook(onDeactivated)
    expect(state.advancedToolsVisible.value).toBe(false)
    await hook(onActivated)
    expect(state.advancedToolsVisible.value).toBe(false)
    state.handleAdvancedToolCommand('open-index')
    expect(state.advancedToolsVisible.value).toBe(true)
    expect(state.queryForm.query).toBe('unsaved recall query')
    expect(state.queryForm.top_k).toBe(12)
  })
  it('closes the edit dialog on deactivation and restores its cached draft when reopened', async () => {
    await hook(onMounted)
    state.inspectorDraft.text = 'unsaved inspector'
    state.openEditDoc(state.docs.value[0])
    Object.assign(state.editForm, { text: 'unsaved dialog', importance: 0.9, metadataJson: '{"draft":true}' })
    const draft = { ...state.editForm }

    await hook(onDeactivated)
    expect(state.editDialogVisible.value).toBe(false)
    await hook(onActivated)
    expect(state.editDialogVisible.value).toBe(false)
    expect(state.inspectorDraft.text).toBe('unsaved inspector')
    expect(state.editForm).toEqual(draft)
    state.openEditDoc(state.docs.value[1])
    state.editDialogVisible.value = false
    state.openEditDoc(state.docs.value[0])
    expect(state.editDialogVisible.value).toBe(true)
    expect(state.editForm).toEqual(draft)
  })
  it('keeps cached rows and dirty inspector/dialog drafts during a background refresh', async () => {
    await hook(onMounted)
    state.inspectorDraft.text = 'unsaved inspector'
    state.openEditDoc(state.docs.value[0])
    state.editForm.text = 'unsaved dialog'
    await hook(onDeactivated)
    const pending = deferred<any>()
    vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : pending.promise)
    await hook(onActivated)
    expect(libraryReads()).toHaveLength(2)
    expect(state.docs.value[0].text).toBe('a')
    expect(state.docsRequest.loading).toBe(true)
    pending.resolve({ docs: [doc('a', 'changed remotely'), doc('b')] })
    await flush()
    expect(state.docs.value[0].text).toBe('changed remotely')
    expect(state.inspectorDraft.text).toBe('unsaved inspector')
    expect(state.editForm.text).toBe('unsaved dialog')
  })
  it('opens edit query changes and consumes each navigation once', async () => {
    await hook(onMounted)
    route.query.edit = 'b'
    await flush()
    expect(state.editForm.id).toBe('b')
    state.editForm.text = 'unsaved b'
    state.editDialogVisible.value = false
    await hook(onDeactivated)
    await hook(onActivated)
    expect(state.editDialogVisible.value).toBe(false)
    route.query.edit = 'a'
    await flush()
    expect(state.editForm.id).toBe('a')
    route.query.edit = 'b'
    await flush()
    expect(state.editForm.text).toBe('unsaved b')
  })
  it('waits for refreshed scoped data on cached edit navigation and honors the latest query', async () => {
    await hook(onMounted)
    await hook(onDeactivated)
    route.name = 'settings'
    await flush()
    const pending = deferred<any>()
    vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : pending.promise)
    route.name = 'memory'
    route.query.edit = 'a'
    await hook(onActivated)
    route.query.edit = 'b'
    await flush()
    expect(state.editDialogVisible.value).toBe(false)
    pending.resolve({ docs: [doc('b', 'fresh b')] })
    await flush()
    expect(state.editDialogVisible.value).toBe(true)
    expect(state.editForm.id).toBe('b')
    expect(state.editForm.text).toBe('fresh b')
    expect(ElMessage.warning).not.toHaveBeenCalled()
  })
  it('rejects old scope responses and their navigation continuations', async () => {
    const old = deferred<any>()
    vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : options?.workspaceId === 'workspace-a' ? old.promise : Promise.resolve({ docs: [doc('a', 'workspace b')] }))
    route.query.edit = 'a'
    await hook(onMounted)
    route.params.workspaceId = 'workspace-b'
    workspace.activeWorkspace.id = 'workspace-b'
    await flush()
    expect(state.editForm.text).toBe('workspace b')
    const statusReads = vi.mocked(memoryClient.getIndexStatus).mock.calls.length
    old.resolve({ docs: [doc('a', 'stale workspace a')] })
    await flush()
    expect(state.docs.value[0].text).toBe('workspace b')
    expect(state.editForm.text).toBe('workspace b')
    expect(memoryClient.getIndexStatus).toHaveBeenCalledTimes(statusReads)
  })
  it('defers scope refresh while inactive and refreshes the latest scope once on return', async () => {
    await hook(onMounted)
    await hook(onDeactivated)
    workspace.activeWorkspace.id = 'workspace-b'
    await flush()
    expect(libraryReads()).toHaveLength(1)
    await hidden(true)
    await hook(onActivated)
    expect(libraryReads()).toHaveLength(1)
    await hidden(false)
    expect(libraryReads()).toHaveLength(2)
    expect(libraryReads()[1][0]?.workspaceId).toBe('workspace-b')
  })
  it('warns once for a missing edit target after a successful read', async () => {
    await hook(onMounted)
    route.query.edit = 'missing'
    await flush()
    expect(ElMessage.warning).toHaveBeenCalledTimes(1)
    await hook(onDeactivated)
    await hook(onActivated)
    expect(ElMessage.warning).toHaveBeenCalledTimes(1)
  })
  it('cleans polling timers and the visibility listener on unmount', async () => {
    vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
    await hook(onMounted)
    await hook(onBeforeUnmount)
    expect(visibility.removeEventListener).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    expect(vi.getTimerCount()).toBe(0)
    await hidden(true)
    await hidden(false)
    await vi.advanceTimersByTimeAsync(2000)
    expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(1)
  })
})


const renderPanel = async () => {
  const app = createSSRApp({ ...MemoryPanel, setup: () => state })
  app.config.warnHandler = () => undefined
  return renderToString(app)
}

it('keeps cached rows rendered while the library refresh is pending', async () => {
  await hook(onMounted)
  await hook(onDeactivated)
  const pending = deferred<any>()
  vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : pending.promise)
  await hook(onActivated)
  const html = await renderPanel()
  expect(html).toContain('data-loading="false"')
  expect(html).toContain('<p>a</p>')
  expect(state.docsRequest.loading).toBe(true)
  pending.resolve({ docs: [doc('a')] })
  await flush()
})

it('does not resolve an edit link against the previous route workspace', async () => {
  await hook(onMounted)
  route.params.workspaceId = 'workspace-b'
  route.query.edit = 'a'
  await flush()
  expect(state.editDialogVisible.value).toBe(false)
  vi.mocked(memoryClient.getDocs).mockResolvedValue({ docs: [doc('a', 'workspace b')] })
  workspace.activeWorkspace.id = 'workspace-b'
  await flush()
  expect(state.editForm.text).toBe('workspace b')
})

it('does not start reads when mounted hidden, then refreshes only once when visible', async () => {
  visibility.hidden = true
  await hook(onMounted)
  await hook(onActivated)
  expect(memoryClient.getDocs).not.toHaveBeenCalled()
  await hidden(false)
  await hook(onActivated)
  expect(libraryReads()).toHaveLength(1)
})

it.each(['cancelled', 'failed', 'interrupted'])('reads the %s terminal state after a hidden interval', async terminal => {
  vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
  await hook(onMounted)
  await hidden(true)
  vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'ok', count: 2, job: job(terminal) } as any)
  await hidden(false)
  expect(state.displayedRebuildJob.value.state).toBe(terminal)
  expect(state.rebuildIndexLoading.value).toBe(false)
  expect(vi.getTimerCount()).toBe(0)
  expect(memoryClient.cancelIndexRebuild).not.toHaveBeenCalled()
})

it('rejects an old poll after resume without disturbing the new monitoring chain', async () => {
  const pending = deferred<any>()
  vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
  vi.mocked(memoryClient.getIndexRebuildJob).mockReturnValueOnce(pending.promise)
  await hook(onMounted)
  await hook(onDeactivated)
  await hook(onActivated)
  pending.resolve({ job: job('completed'), index_status: 'ok' })
  await flush()
  expect(state.displayedRebuildJob.value.state).toBe('running')
  expect(state.rebuildIndexLoading.value).toBe(true)
  await vi.advanceTimersByTimeAsync(500)
  expect(memoryClient.getIndexRebuildJob).toHaveBeenCalledTimes(3)
  expect(vi.getTimerCount()).toBe(1)
})

it('keeps a failed cached refresh visible and retries an unconsumed edit link', async () => {
  await hook(onMounted)
  await hook(onDeactivated)
  route.query.edit = 'a'
  const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
  vi.mocked(memoryClient.getDocs).mockImplementation(options => options?.includeState === 'forgotten' ? Promise.resolve({ docs: [] }) : Promise.reject(new Error('offline')))
  try {
    await hook(onActivated)
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(state.editDialogVisible.value).toBe(false)
    const html = await renderPanel()
    expect(html).toContain('data-error="none"')
    expect(html).toContain('<p>a</p>')
    vi.mocked(memoryClient.getDocs).mockResolvedValue({ docs: [doc('a', 'recovered')] })
    await state.refreshMemoryState()
    await flush()
    expect(state.editForm.text).toBe('recovered')
  } finally { logging.mockRestore() }
})

it('releases paused rebuild waiting even when the resumed status request fails', async () => {
  vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ status: 'rebuilding', count: 2, job: job('running') } as any)
  await hook(onMounted)
  expect(state.rebuildIndexLoading.value).toBe(true)
  await hook(onDeactivated)
  expect(state.rebuildIndexLoading.value).toBe(false)
  vi.mocked(memoryClient.getIndexStatus).mockRejectedValue(new Error('offline'))
  await hook(onActivated)
  expect(state.rebuildIndexLoading.value).toBe(false)
  expect(state.indexStatus.value.status).toBe('error')
  expect(vi.getTimerCount()).toBe(0)
})

vi.mock('element-plus/es/components/skeleton/style/css', () => ({}))
vi.mock('element-plus/es/components/collapse-item/style/css', () => ({}))
vi.mock('element-plus/es/components/collapse/style/css', () => ({}))
vi.mock('element-plus/es/components/tag/style/css', () => ({}))
vi.mock('element-plus/es/components/card/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('element-plus/es/components/empty/style/css', () => ({}))
vi.mock('element-plus/es/components/alert/style/css', () => ({}))
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRenderer, defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import InfrastructurePanel from './InfrastructurePanel.vue'
import { systemClient } from '@/api/client'

vi.mock('vue', async (original) => ({ ...await original<typeof import('vue')>(), useSSRContext: () => ({ modules: new Set() }) }))
vi.mock('@/stores/workspaceStore', async () => {
  const { reactive } = await import('vue')
  return { useWorkspaceStore: () => reactive({ activeWorkspace: { id: 'alpha' } }) }
})
vi.mock('element-plus', async (original) => ({ ...await original<typeof import('element-plus')>(), ElMessage: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('@/shared/components/feedback/AsyncState.vue', () => ({ default: {} }))
vi.mock('@/domains/deploy/views/DeployPanel.vue', () => ({ default: {} }))
vi.mock('@/utils/petControl', () => ({ petControl: {} }))
vi.mock('@/i18n', () => ({ t: (key: string) => key, currentLocale: 'zh-CN' }))
vi.mock('@/api/client', () => ({ systemClient: {
  diagnostics: vi.fn(), backupTargets: vi.fn(), logs: vi.fn(), systemStatus: vi.fn(), databaseStats: vi.fn(), statistics: vi.fn(), models: vi.fn(), effectivePreset: vi.fn(), updateStatistics: vi.fn(),
} }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
// A real Vue renderer exercises KeepAlive hooks and watch scheduling without a DOM.
interface TestNode { parent: TestNode | null; children: TestNode[] }
const node = (): TestNode => ({ parent: null, children: [] })
const detach = (child: TestNode) => {
  if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}
const renderer = createRenderer<TestNode, TestNode>({
  createElement: node, createText: node, createComment: node,
  setText() {}, setElementText() {}, patchProp() {},
  parentNode: (child) => child.parent,
  nextSibling: (child) => child.parent?.children[child.parent.children.indexOf(child) + 1] ?? null,
  insert(child, parent, anchor) {
    detach(child)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    child.parent = parent
  },
  remove: detach,
})
const snapshotClients = [systemClient.systemStatus, systemClient.databaseStats, systemClient.statistics, systemClient.models, systemClient.effectivePreset]
let app: ReturnType<typeof renderer.createApp>
let visible: ReturnType<typeof ref<boolean>>
let state: any
let setups: number
const show = async (value: boolean) => { visible.value = value; await nextTick() }
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('window', {})
  for (const client of snapshotClients) vi.mocked(client).mockResolvedValue({})
  vi.mocked(systemClient.diagnostics).mockResolvedValue({} as any)
  vi.mocked(systemClient.backupTargets).mockResolvedValue({ targets: [] } as any)
  vi.mocked(systemClient.logs).mockResolvedValue({} as any)
  setups = 0
  visible = ref(true)
  const panel = defineComponent({
    name: 'InfrastructurePanelLifecycleHarness',
    setup(props, context) {
      setups += 1
      state = (InfrastructurePanel as any).setup(props, context)
      return state
    },
    render: () => null,
  })
  const other = defineComponent({ render: () => null })
  app = renderer.createApp({
    render: () => h(KeepAlive, null, { default: () => visible.value ? h(panel) : h(other) }),
  })
  app.mount(node())
})
afterEach(() => { app.unmount(); vi.unstubAllGlobals() })

it('does not clear a new workspace snapshot spinner or inject an old statistics error', async () => {
  await state.loadApiGaps()
  const update = deferred<any>()
  const snapshot = deferred<any>()
  vi.mocked(systemClient.updateStatistics).mockReturnValue(update.promise)
  vi.mocked(systemClient.effectivePreset).mockReturnValue(snapshot.promise)
  const updating = state.updateStats()
  state.workspaceStore.activeWorkspace.id = 'beta'
  await nextTick()
  expect(systemClient.effectivePreset).toHaveBeenLastCalledWith('beta')
  update.reject(new Error('old workspace update failed'))
  await updating
  expect(state.apiGapLoading.value).toBe(true)
  expect(state.apiGapError.value).toBe('')
  snapshot.resolve({ workspaceId: 'beta' })
  await vi.waitFor(() => expect(state.apiGapLoading.value).toBe(false))
  expect(state.effectivePreset.value).toEqual({ workspaceId: 'beta' })
})


it('keeps unopened API snapshots lazy through cached workspace switches', async () => {
  expect(snapshotClients.every((client) => vi.mocked(client).mock.calls.length === 0)).toBe(true)
  await show(false)
  state.workspaceStore.activeWorkspace.id = 'beta'
  await nextTick()
  await show(true)
  expect(setups).toBe(1)
  expect(snapshotClients.every((client) => vi.mocked(client).mock.calls.length === 0)).toBe(true)
})

it('sends no snapshot requests while cached and reloads all five once for the current workspace on activation', async () => {
  await state.loadApiGaps()
  const cachedState = state
  await show(false)
  state.workspaceStore.activeWorkspace.id = 'beta'
  await nextTick()
  state.workspaceStore.activeWorkspace.id = 'gamma'
  await nextTick()
  for (const client of snapshotClients) expect(client).toHaveBeenCalledOnce()
  await state.loadApiGaps()
  for (const client of snapshotClients) expect(client).toHaveBeenCalledOnce()
  await show(true)
  await vi.waitFor(() => expect(state.apiGapLoading.value).toBe(false))
  for (const client of snapshotClients) expect(client).toHaveBeenCalledTimes(2)
  expect(systemClient.effectivePreset).toHaveBeenLastCalledWith('gamma')
  expect(state).toBe(cachedState)
  expect(setups).toBe(1)
})

it('invalidates an interrupted first snapshot and its errors while deactivated, then retries it on activation', async () => {
  const pending = snapshotClients.map(() => deferred<any>())
  snapshotClients.forEach((client, index) => vi.mocked(client).mockReturnValueOnce(pending[index].promise))
  const loading = state.loadApiGaps()
  await show(false)
  pending[0].reject(new Error('inactive status failure'))
  for (const item of pending.slice(1)) item.resolve({ workspaceId: 'old' })
  await loading
  expect(state.systemStatus.value).toBeNull()
  expect(state.effectivePreset.value).toBeNull()
  expect(state.apiGapError.value).toBe('')
  expect(state.apiGapLoading.value).toBe(false)
  expect(state.apiGapLoaded.value).toBe(false)
  await show(true)
  await vi.waitFor(() => expect(state.apiGapLoaded.value).toBe(true))
  for (const client of snapshotClients) expect(client).toHaveBeenCalledTimes(2)
})

it('rejects a previous activation reply even after returning to the same workspace', async () => {
  const older = deferred<any>()
  const newer = deferred<any>()
  vi.mocked(systemClient.effectivePreset).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
  const loading = state.loadApiGaps()
  await show(false)
  await show(true)
  older.resolve({ workspaceId: 'alpha', revision: 'old' })
  await loading
  expect(state.effectivePreset.value).toBeNull()
  expect(state.apiGapLoading.value).toBe(true)
  newer.resolve({ workspaceId: 'alpha', revision: 'new' })
  await vi.waitFor(() => expect(state.apiGapLoading.value).toBe(false))
  expect(state.effectivePreset.value).toEqual({ workspaceId: 'alpha', revision: 'new' })
})

it.each([false, true])('discards an old statistics update after deactivation (failure: %s)', async (fails) => {
  await state.loadApiGaps()
  const update = deferred<any>()
  vi.mocked(systemClient.updateStatistics).mockReturnValueOnce(update.promise)
  const updating = state.updateStats()
  await show(false)
  if (fails) update.reject(new Error('inactive update failed'))
  else update.resolve({})
  await updating
  expect(state.apiGapError.value).toBe('')
  for (const client of snapshotClients) expect(client).toHaveBeenCalledOnce()
  await show(true)
  await vi.waitFor(() => expect(state.apiGapLoading.value).toBe(false))
  for (const client of snapshotClients) expect(client).toHaveBeenCalledTimes(2)
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { computed, reactive, ref } from 'vue'
import { panelDeclarations } from '../../tools/tests/panel-script.mjs'

const compiled = panelDeclarations(new URL('./PetControlPanel.vue', import.meta.url), ['scheduleReadyRetry'])
afterEach(() => vi.useRealTimers())

describe('pet model readiness recovery', () => {
  it('reads capabilities again after the renderer finishes loading a model', async () => {
    vi.useFakeTimers()
    const state = reactive({ ready: false })
    const capabilities = { modelId: 'loaded-model', actions: { motion: true } }
    const env = {
      window: { setTimeout }, readyRetryTimer: null, clearReadyRetry: vi.fn(),
      pageLifecycle: { active: ref(true) }, state, readyRetryCount: 0, refreshSequence: 1, stateWriteSequence: 0, operationLoading: ref(false),
      petControl: { getState: vi.fn().mockResolvedValue({ ready: true }), getAvatarCapabilities: vi.fn().mockResolvedValue({ success: true, capabilities }) },
      avatarReady: computed(() => Boolean(env.state.ready && env.avatarCapabilities.value)),
      avatarCapabilities: ref(null), applyState: (next: object) => Object.assign(state, next), syncDrafts: vi.fn(),
    }
    const schedule = new Function(...Object.keys(env), `${compiled}; return scheduleReadyRetry`)(...Object.values(env))
    schedule()
    await vi.advanceTimersByTimeAsync(500)
    expect(state.ready).toBe(true)
    expect(env.avatarCapabilities.value).toEqual(capabilities)
    expect(env.petControl.getAvatarCapabilities).toHaveBeenCalledOnce()
    expect(env.syncDrafts).toHaveBeenCalledOnce()
  })

  it('keeps retrying if capabilities are temporarily unavailable even after state becomes ready', async () => {
    vi.useFakeTimers()
    const env = {
      window: { setTimeout }, readyRetryTimer: null, clearReadyRetry: vi.fn(),
      pageLifecycle: { active: ref(true) }, state: reactive({ ready: false }), readyRetryCount: 0, refreshSequence: 1, stateWriteSequence: 0, operationLoading: ref(false),
      petControl: { getState: vi.fn().mockResolvedValue({ ready: true }), getAvatarCapabilities: vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValue({ capabilities: { modelId: 'loaded-model' } }) },
      avatarReady: computed(() => Boolean(env.state.ready && env.avatarCapabilities.value)),
      avatarCapabilities: ref(null), applyState: (next: object) => Object.assign(env.state, next), syncDrafts: vi.fn(),
    }
    const schedule = new Function(...Object.keys(env), `${compiled}; return scheduleReadyRetry`)(...Object.values(env))
    schedule()
    await vi.advanceTimersByTimeAsync(1000)
    expect(env.petControl.getAvatarCapabilities).toHaveBeenCalledTimes(2)
    expect(env.avatarCapabilities.value).toEqual({ modelId: 'loaded-model' })
  })
})

const operationCode = panelDeclarations(new URL('./PetControlPanel.vue', import.meta.url), [
  'clearReadyRetry', 'scheduleReadyRetry', 'runPetOperation', 'applyState', 'refresh', 'applyScale',
])
const deferred = <T,>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
const setupOperations = () => {
  const state = reactive({ ready: false, modelId: 'model-a', scale: 0.3 })
  const env = {
    window: { setTimeout, clearTimeout }, readyRetryTimer: null, readyRetryCount: 0,
    refreshSequence: 0, stateWriteSequence: 0,
    pageLifecycle: { active: ref(true) }, hostCapability: ref({ available: true }),
    refreshingPet: ref(false), operationLoading: ref(false), pendingAction: ref(null),
    operationMessage: ref(''), operationAlertType: ref('info'), state,
    catalog: reactive({ activeModelId: null, models: [] }), displays: reactive({ activeDisplayId: null, items: [] }),
    placementPresets: ref([]), hasLoadedState: ref(false), avatarCapabilities: ref<{ modelId: string } | null>(null),
    avatarReady: computed(() => Boolean(state.ready && env.avatarCapabilities.value?.modelId === state.modelId)),
    catalogLoadError: ref(''), displayLoadError: ref(''),
    t: (key: string) => key, ElMessage: { warning: vi.fn(), error: vi.fn() },
    errorMessage: (error: Error) => error.message, syncDrafts: vi.fn(),
    petControl: {
      getState: vi.fn().mockResolvedValue({ ready: true, modelId: 'model-a', scale: 0.4 }),
      getCatalog: vi.fn().mockResolvedValue({ activeModelId: 'model-a', models: [{ id: 'model-a' }] }),
      getDisplays: vi.fn().mockResolvedValue({ activeDisplayId: 1, displays: [{ id: 1 }] }),
      getPlacementPresets: vi.fn().mockResolvedValue({ presets: [{ id: 'bottom-right' }] }),
      getAvatarCapabilities: vi.fn().mockResolvedValue({ capabilities: { modelId: 'model-a' } }),
      setScale: vi.fn().mockImplementation(async (scale: number) => ({ ...state, scale })),
    },
  }
  const panel = new Function(...Object.keys(env), `${operationCode}; return { refresh, applyScale, scheduleReadyRetry }`)(...Object.values(env))
  return { env, panel }
}

describe('pet writes during readiness reads', () => {
  it('keeps independent first-refresh results without reverting a completed scale write', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    const read = deferred<object>()
    env.petControl.getState.mockReturnValueOnce(read.promise)
    const refresh = panel.refresh()
    await panel.applyScale(0.5)
    expect(env.refreshingPet.value).toBe(true)
    read.resolve({ ready: false, modelId: 'model-a', scale: 0.3 })
    await refresh
    expect(env.catalog.models).toEqual([{ id: 'model-a' }])
    expect(env.displays.items).toEqual([{ id: 1 }])
    expect(env.placementPresets.value).toEqual([{ id: 'bottom-right' }])
    expect(env.avatarCapabilities.value).toEqual({ modelId: 'model-a' })
    expect(env.hasLoadedState.value).toBe(true)
    expect(env.state.scale).toBe(0.5)
    expect(env.refreshingPet.value).toBe(false)
    await vi.advanceTimersByTimeAsync(500)
    expect(env.state.ready).toBe(true)
  })

  it('continues an already scheduled readiness retry after a scale write', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    panel.scheduleReadyRetry()
    await panel.applyScale(0.4)
    await vi.advanceTimersByTimeAsync(500)
    expect(env.petControl.getState).toHaveBeenCalledOnce()
    expect(env.state.ready).toBe(true)
    expect(env.avatarCapabilities.value).toEqual({ modelId: 'model-a' })
  })

  it('accepts late retry capabilities without letting its old state overwrite a newer write', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    const read = deferred<object>()
    env.petControl.getState.mockReturnValueOnce(read.promise)
    panel.scheduleReadyRetry()
    await vi.advanceTimersByTimeAsync(500)
    await panel.applyScale(0.5)
    read.resolve({ ready: false, modelId: 'model-a', scale: 0.3 })
    await vi.advanceTimersByTimeAsync(0)
    expect(env.state.scale).toBe(0.5)
    expect(env.avatarCapabilities.value).toEqual({ modelId: 'model-a' })
    await vi.advanceTimersByTimeAsync(500)
    expect(env.state.ready).toBe(true)
  })

  it('defers readiness state reads while a write is pending and resumes them afterwards', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    const write = deferred<object>()
    env.petControl.setScale.mockReturnValueOnce(write.promise)
    panel.scheduleReadyRetry()
    const operation = panel.applyScale(0.4)
    await vi.advanceTimersByTimeAsync(500)
    expect(env.petControl.getState).not.toHaveBeenCalled()
    write.resolve({ ready: false, modelId: 'model-a', scale: 0.4 })
    await operation
    await vi.advanceTimersByTimeAsync(500)
    expect(env.petControl.getState).toHaveBeenCalledOnce()
    expect(env.state.ready).toBe(true)
  })

  it('resumes readiness synchronization after a failed operation', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    panel.scheduleReadyRetry()
    env.petControl.setScale.mockRejectedValueOnce(new Error('write failed'))
    await panel.applyScale(0.4)
    await vi.advanceTimersByTimeAsync(500)
    expect(env.operationMessage.value).toBe('write failed')
    expect(env.state.ready).toBe(true)
  })

  it('keeps independent refresh results arriving while a write is still pending', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    const read = deferred<object>()
    const write = deferred<object>()
    env.petControl.getState.mockReturnValueOnce(read.promise)
    env.petControl.setScale.mockReturnValueOnce(write.promise)
    const refresh = panel.refresh()
    const operation = panel.applyScale(0.4)
    read.resolve({ ready: true, modelId: 'model-a', scale: 0.2 })
    await refresh
    expect(env.state.scale).toBe(0.3)
    expect(env.state.ready).toBe(false)
    expect(env.catalog.models).toEqual([{ id: 'model-a' }])
    expect(env.avatarCapabilities.value).toEqual({ modelId: 'model-a' })
    write.resolve({ ready: false, modelId: 'model-a', scale: 0.4 })
    await operation
    await vi.advanceTimersByTimeAsync(500)
    expect(env.state.scale).toBe(0.4)
    expect(env.state.ready).toBe(true)
  })

  it('retains the four-attempt bound when readiness remains unavailable', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    env.petControl.getState.mockResolvedValue({ ready: false, modelId: 'model-a', scale: 0.4 })
    env.petControl.getAvatarCapabilities.mockRejectedValue(new Error('not ready'))
    panel.scheduleReadyRetry()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(env.petControl.getState).toHaveBeenCalledTimes(4)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('discards pending reads after the panel becomes inactive', async () => {
    vi.useFakeTimers()
    const { env, panel } = setupOperations()
    const read = deferred<object>()
    env.petControl.getState.mockReturnValueOnce(read.promise)
    const refresh = panel.refresh()
    env.pageLifecycle.active.value = false
    read.resolve({ ready: true, modelId: 'model-a', scale: 0.3 })
    await refresh
    expect(env.catalog.models).toEqual([])
    expect(env.avatarCapabilities.value).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })
})

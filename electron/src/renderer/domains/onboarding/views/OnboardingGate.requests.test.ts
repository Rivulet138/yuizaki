import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { panelDeclarations } from '../../tools/tests/panel-script.mjs'

const compiled = panelDeclarations(new URL('./OnboardingGate.vue', import.meta.url), ['schedulePoll', 'applySnapshot', 'loadSnapshot'])
const snapshot = (revision: number, operation = 'probe_scan', runId = 'run-a') => ({ revision, operation, runId, probes: [] })
const setup = () => {
  const env = {
    window: { setTimeout }, pollTimer: null, disposed: false,
    snapshot: ref(snapshot(4)), runActive: ref(true), emptyIdlePollCount: 0, MAX_EMPTY_IDLE_POLLS: 10,
    loading: ref(false), loadError: ref(''),
    onboardingApi: ref({ snapshot: vi.fn() }), t: (key: string) => key,
    messageFrom: (error: Error) => error.message,
  }
  const state = new Function(...Object.keys(env), `${compiled}; return { loadSnapshot, applySnapshot, dispose: () => { disposed = true } }`)(...Object.values(env))
  return { env, state }
}
afterEach(() => vi.useRealTimers())

describe('onboarding readiness polling', () => {
  it('continues polling after a transient snapshot failure', async () => {
    vi.useFakeTimers()
    const { env, state } = setup()
    env.onboardingApi.value.snapshot.mockRejectedValueOnce(new Error('temporarily offline')).mockResolvedValue(snapshot(5, 'idle'))
    await state.loadSnapshot(false)
    expect(env.loadError.value).toBe('temporarily offline')
    env.runActive.value = false
    await vi.advanceTimersByTimeAsync(900)
    expect(env.onboardingApi.value.snapshot).toHaveBeenCalledTimes(2)
    expect(env.snapshot.value.revision).toBe(5)
    expect(env.loadError.value).toBe('')
  })

  it('rejects an old run response after a newer run snapshot was accepted', () => {
    vi.useFakeTimers()
    const { env, state } = setup()
    state.applySnapshot(snapshot(8, 'idle', 'run-b'))
    state.applySnapshot(snapshot(7, 'probe_scan', 'run-a'))
    expect(env.snapshot.value).toEqual(snapshot(8, 'idle', 'run-b'))
  })

  it('does not restart timers when an in-flight read returns after unmount', async () => {
    vi.useFakeTimers()
    const { env, state } = setup()
    let resolve!: (value: unknown) => void
    env.onboardingApi.value.snapshot.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const pending = state.loadSnapshot(false)
    state.dispose()
    resolve(snapshot(8))
    await pending
    expect(vi.getTimerCount()).toBe(0)
    expect(env.snapshot.value.revision).toBe(4)
  })
})

const browserApiCode = panelDeclarations(new URL('./OnboardingGate.vue', import.meta.url), ['browserOnboardingApi'])
const setupBrowserApi = () => {
  const requestJson = vi.fn().mockResolvedValue(snapshot(5, 'idle'))
  const api = new Function('requestJson', 'CONTROL_ORIGIN', `${browserApiCode}; return browserOnboardingApi`)(requestJson, 'http://localhost:38945')
  return { api, requestJson }
}

describe('browser onboarding repair deadlines', () => {
  it('gives backend repair the same startup deadline as the direct start action', async () => {
    const { api, requestJson } = setupBrowserApi()
    await api.startBackend()
    const startOptions = requestJson.mock.calls[0][1]
    await api.runRepair({ actionId: 'backend.retry' })
    expect(requestJson).toHaveBeenLastCalledWith('http://localhost:38945/api/onboarding/repair', {
      method: 'POST', body: JSON.stringify({ actionId: 'backend.retry' }), timeoutMs: startOptions.timeoutMs,
    })
    expect(startOptions.timeoutMs).toBe(180_000)
  })

  it.each(['probe.retry:llm.provider', 'probe.retry:host.avatar'])(
    'gives %s the same deadline as probe retry', async actionId => {
      const { api, requestJson } = setupBrowserApi()
      await api.retry({ runId: 'run-a' })
      const retryOptions = requestJson.mock.calls[0][1]
      await api.runRepair({ actionId })
      expect(requestJson.mock.calls[1][1].timeoutMs).toBe(retryOptions.timeoutMs)
      expect(retryOptions.timeoutMs).toBe(35_000)
    },
  )

  it.each(['avatar.reload', 'mcp.refresh_existing', 'logs.open', 'guide.open', 'navigate:chat', 'resource.prepare:tts'])(
    'keeps the default request deadline for %s', async actionId => {
      const { api, requestJson } = setupBrowserApi()
      await api.runRepair({ actionId })
      expect(requestJson.mock.calls[0][1].timeoutMs).toBeUndefined()
    },
  )
})

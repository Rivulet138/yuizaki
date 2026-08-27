import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OnboardingProbeId, OnboardingProbeResult, OnboardingReadinessSnapshot } from '../../shared/onboarding-readiness'
import OnboardingGate from '../domains/onboarding/views/OnboardingGate.vue'
import { setLocale } from '../i18n'

const probe = (
  id: OnboardingProbeId,
  status: OnboardingProbeResult['status'],
  overrides: Partial<OnboardingProbeResult> = {},
): OnboardingProbeResult => ({
  id,
  label: id,
  status,
  requiredForText: ['host.runtime', 'backend.service', 'llm.provider', 'llm.model_chat'].includes(id),
  dependencies: [],
  timeoutMs: 1_000,
  message: `${id} ${status}`,
  evidence: {},
  repairActionId: null,
  ...overrides,
})

const createSnapshot = (overrides: Partial<OnboardingReadinessSnapshot> = {}): OnboardingReadinessSnapshot => ({
  schemaVersion: 1,
  runId: 'run-1',
  revision: 1,
  state: 'blocked',
  operation: 'idle',
  readyForText: false,
  startedAt: null,
  completedAt: null,
  probes: [
    probe('host.runtime', 'ready'),
    probe('backend.service', 'failed'),
    probe('llm.provider', 'needs_user'),
    probe('llm.model_chat', 'needs_user'),
    probe('tts.status', 'failed', { requiredForText: false }),
  ],
  ...overrides,
})

const createApi = (initial: OnboardingReadinessSnapshot) => ({
  snapshot: vi.fn().mockResolvedValue(initial),
  startBackend: vi.fn().mockResolvedValue(initial),
  cancelBackend: vi.fn().mockResolvedValue({ ...initial, state: 'cancelled' }),
  cancelRun: vi.fn().mockResolvedValue({ ...initial, state: 'cancelled' }),
  reportDeviceProbe: vi.fn().mockResolvedValue(initial),
  runProbe: vi.fn().mockResolvedValue(initial),
  retry: vi.fn().mockResolvedValue(initial),
  runRepair: vi.fn().mockResolvedValue(initial),
})

const global = {
  stubs: {
    PanelShell: { template: '<main><header><slot name="actions" /></header><slot /></main>' },
    AsyncState: { template: '<div><slot /></div>' },
    OnboardingModelSetup: { template: '<div class="model-setup-stub" />' },
    'el-button': {
      props: ['disabled', 'loading', 'type'],
      emits: ['click'],
      template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
    },
    'el-icon': { template: '<i><slot /></i>' },
    'el-select': { template: '<select><slot /></select>' },
    'el-option': { template: '<option />' },
  },
}

const installApi = (api: ReturnType<typeof createApi>): void => {
  Object.defineProperty(window, 'petApi', { configurable: true, value: { onboarding: api } })
}

const installTrustedE2EApi = (api: ReturnType<typeof createApi>): void => {
  Object.defineProperty(window, 'petApi', { configurable: true, value: { onboarding: api, e2e: Object.freeze({}) } })
}

describe('OnboardingGate', () => {
  beforeEach(async () => {
    window.localStorage.clear()
    vi.clearAllMocks()
    await setLocale('zh-CN', { persistSettings: false })
  })

  it('renders a backend-down first-run gate with a keyboard-focusable start action', async () => {
    const api = createApi(createSnapshot())
    installApi(api)
    const wrapper = mount(OnboardingGate, {
      attachTo: document.body,
      global,
      slots: { default: '<div class="application">app</div>' },
    })
    await flushPromises()

    expect(wrapper.find('.application').exists()).toBe(false)
    expect(wrapper.text()).toContain('启动本地服务')
    expect(wrapper.text()).toContain('此项目检查失败，请重试。')
    expect(wrapper.findAll('[role="status"]')).toHaveLength(1)
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(1)
    expect(wrapper.find('.window-actions').exists()).toBe(false)
    expect(wrapper.find('.onboarding-page').attributes('style')).toContain('--onboarding-wallpaper:')
    const startButton = wrapper.findAll('button').find(button => button.text().includes('启动本地服务'))
    expect(startButton).toBeDefined()
    startButton!.element.focus()
    expect(document.activeElement).toBe(startButton!.element)
    wrapper.unmount()
  })

  it('lets a first-run user skip the gate and enter the application', async () => {
    const api = createApi(createSnapshot())
    installApi(api)
    const wrapper = mount(OnboardingGate, {
      global,
      slots: { default: '<div class="application">app</div>' },
    })
    await flushPromises()

    const skipButton = wrapper.findAll('button').find(button => button.text().includes('跳过并进入应用'))
    expect(skipButton).toBeDefined()
    await skipButton!.trigger('click')

    expect(window.localStorage.getItem('yuizaki.onboarding.completed.v1')).toBe('true')
    expect(wrapper.find('.application').exists()).toBe(true)
    expect(wrapper.find('.onboarding-page').exists()).toBe(false)
  })

  it('exposes Electron window controls on the first-run page', async () => {
    const api = createApi(createSnapshot())
    const windowActions = {
      minimize: vi.fn(),
      maximize: vi.fn(),
      close: vi.fn(),
    }
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: { onboarding: api, window: windowActions },
    })
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    const controls = wrapper.find('.window-actions')
    expect(controls.exists()).toBe(true)
    await controls.find('button[aria-label="最小化"]').trigger('click')
    await controls.find('button[aria-label="最大化"]').trigger('click')
    await controls.find('button[aria-label="关闭"]').trigger('click')

    expect(windowActions.minimize).toHaveBeenCalledOnce()
    expect(windowActions.maximize).toHaveBeenCalledOnce()
    expect(windowActions.close).toHaveBeenCalledOnce()
  })

  it('bypasses first-run gating only for the trusted preload E2E activation surface', async () => {
    const api = createApi(createSnapshot())
    installTrustedE2EApi(api)
    const wrapper = mount(OnboardingGate, {
      global,
      slots: { default: '<div class="application">app</div>' },
    })
    await flushPromises()

    expect(window.localStorage.getItem('yuizaki.onboarding.completed.v1')).toBeNull()
    expect(wrapper.find('.application').exists()).toBe(true)
    expect(wrapper.find('.onboarding-page').exists()).toBe(false)
    expect(api.snapshot).not.toHaveBeenCalled()
  })

  it('allows text-only readiness while optional services remain degraded', async () => {
    const ready = createSnapshot({
      state: 'ready',
      readyForText: true,
      probes: [
        probe('host.runtime', 'ready'),
        probe('backend.service', 'ready'),
        probe('llm.provider', 'ready'),
        probe('llm.model_chat', 'ready'),
        probe('tts.status', 'degraded', { requiredForText: false, durationMs: 37 }),
        probe('asr.runtime', 'unavailable', { requiredForText: false }),
      ],
    })
    installApi(createApi(ready))
    const wrapper = mount(OnboardingGate, { global, slots: { default: '<div class="application">app</div>' } })
    await flushPromises()

    expect(wrapper.text()).toContain('文本对话已就绪')
    expect(wrapper.text()).toContain('可选功能')
    expect(wrapper.text()).toContain('功能受限')
    expect(wrapper.text()).toContain('本次检查耗时 37 ms')
    expect(wrapper.text()).toContain('当前不可用')
    expect(wrapper.findAll('[role="status"]')).toHaveLength(1)
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(0)
    const chatButton = wrapper.findAll('button').find(button => button.text().includes('开始对话'))!
    expect(chatButton.attributes('disabled')).toBeUndefined()
    await chatButton.trigger('click')
    expect(wrapper.find('.application').exists()).toBe(true)
  })

  it('announces a required unavailable probe as an alert', async () => {
    const snapshot = createSnapshot({
      probes: [
        probe('host.runtime', 'unavailable'),
        probe('backend.service', 'ready'),
        probe('llm.provider', 'ready'),
        probe('llm.model_chat', 'ready'),
      ],
    })
    installApi(createApi(snapshot))
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    expect(wrapper.findAll('[role="status"]')).toHaveLength(1)
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(1)
    expect(wrapper.find('[role="alert"]').attributes('data-required')).toBe('true')
  })

  it('supports optional skip, failed retry, and active-run cancellation', async () => {
    const blocked = createSnapshot()
    const api = createApi(blocked)
    installApi(api)
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    await wrapper.findAll('button').find(button => button.text().includes('稍后设置'))!.trigger('click')
    expect(wrapper.text()).toContain('已跳过可选检查')
    await wrapper.findAll('button').find(button => button.text().includes('重试未就绪项'))!.trigger('click')
    expect(api.retry).toHaveBeenCalledWith(expect.objectContaining({
      runId: 'run-1',
      probeIds: expect.arrayContaining(['backend.service', 'tts.status']),
    }))

    api.snapshot.mockResolvedValue({ ...blocked, state: 'running', operation: 'probe_scan' })
    window.dispatchEvent(new CustomEvent('yuizaki:open-onboarding'))
    await flushPromises()
    expect(wrapper.text()).toContain('取消检查')
    await wrapper.findAll('button').find(button => button.text().includes('取消检查'))!.trigger('click')
    expect(api.cancelRun).toHaveBeenCalledWith({ runId: 'run-1' })
  })

  it('runs the complete voice provider chain only after an explicit user action', async () => {
    const ready = createSnapshot({
      state: 'ready',
      readyForText: true,
      probes: [
        probe('host.runtime', 'ready'),
        probe('backend.service', 'ready'),
        probe('llm.provider', 'ready'),
        probe('llm.model_chat', 'ready'),
        probe('tts.status', 'degraded', { requiredForText: false }),
        probe('asr.runtime', 'unavailable', { requiredForText: false }),
      ],
    })
    const api = createApi(ready)
    installApi(api)
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    const voiceButton = wrapper.findAll('button').find(button => button.text().includes('测试语音链路'))
    expect(voiceButton).toBeDefined()
    expect(api.runProbe).not.toHaveBeenCalled()
    await voiceButton!.trigger('click')
    await flushPromises()

    expect(api.runProbe).toHaveBeenCalledWith({
      probeIds: ['llm.provider', 'llm.model_chat', 'tts.status', 'asr.runtime'],
    })
    wrapper.unmount()
  })

  it('polls an empty idle startup snapshot until main publishes a terminal backend state', async () => {
    vi.useFakeTimers()
    try {
      const idle = createSnapshot({ runId: '', revision: 0, state: 'idle', operation: 'idle', probes: [] })
      const failed = createSnapshot({
        revision: 1,
        state: 'blocked',
        operation: 'idle',
        probes: [probe('backend.service', 'failed')],
      })
      const api = createApi(idle)
      api.snapshot.mockResolvedValueOnce(idle).mockResolvedValue(failed)
      installApi(api)
      const wrapper = mount(OnboardingGate, { global })
      await flushPromises()

      expect(wrapper.text()).toContain('启动本地服务')
      await vi.advanceTimersByTimeAsync(900)
      await flushPromises()

      expect(api.snapshot).toHaveBeenCalledTimes(2)
      expect(wrapper.text()).toContain('此项目检查失败，请重试。')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('can cancel an unresolved backend start and ignores its late result', async () => {
    vi.useFakeTimers()
    try {
      const idle = createSnapshot({ runId: '', revision: 0, state: 'idle', operation: 'idle', probes: [] })
      const running = createSnapshot({
        runId: '', revision: 1, state: 'running', operation: 'backend_start',
        probes: [probe('backend.service', 'running')],
      })
      const cancelled = createSnapshot({
        runId: '', revision: 2, state: 'cancelled', operation: 'idle',
        probes: [probe('backend.service', 'cancelled')],
      })
      const lateReady = createSnapshot({
        revision: 3, state: 'ready', operation: 'idle', readyForText: true,
        probes: [probe('backend.service', 'ready')],
      })
      let resolveStart: ((snapshot: OnboardingReadinessSnapshot) => void) | undefined
      const api = createApi(idle)
      api.startBackend.mockImplementation(() => new Promise(resolve => { resolveStart = resolve }))
      api.snapshot.mockResolvedValueOnce(idle).mockResolvedValue(running)
      api.cancelBackend.mockResolvedValue(cancelled)
      installApi(api)
      const wrapper = mount(OnboardingGate, { global })
      await flushPromises()

      await wrapper.findAll('button').find(button => button.text().includes('启动本地服务'))!.trigger('click')
      expect(wrapper.text()).toContain('取消启动')
      await vi.advanceTimersByTimeAsync(900)
      await flushPromises()
      expect(wrapper.text()).toContain('取消启动')
      await wrapper.findAll('button').find(button => button.text().includes('取消启动'))!.trigger('click')
      await flushPromises()

      expect(api.cancelBackend).toHaveBeenCalledOnce()
      expect(api.cancelRun).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('此项目的检查已取消。')
      resolveStart?.(lateReady)
      await flushPromises()
      expect(wrapper.text()).toContain('此项目的检查已取消。')
      expect(wrapper.text()).not.toContain('此项目已就绪。')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('suppresses unknown repair actions and invokes only shared-contract actions', async () => {
    const snapshot = createSnapshot({
      probes: [
        probe('host.runtime', 'failed', { repairActionId: 'shell.exec:rm' as never }),
        probe('backend.service', 'failed', { repairActionId: 'backend.retry' }),
        probe('llm.provider', 'needs_user'),
        probe('llm.model_chat', 'needs_user'),
      ],
    })
    const api = createApi(snapshot)
    installApi(api)
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    const repairs = wrapper.findAll('button').filter(button => button.text().includes('执行安全修复'))
    expect(repairs).toHaveLength(1)
    await repairs[0]!.trigger('click')
    expect(api.runRepair).toHaveBeenCalledWith({ actionId: 'backend.retry' })
  })

  it('opens model settings from an unresolved model probe without keeping the gate mounted', async () => {
    const snapshot = createSnapshot({
      probes: [
        probe('host.runtime', 'ready'),
        probe('backend.service', 'ready'),
        probe('llm.provider', 'needs_user'),
        probe('llm.model_chat', 'needs_user'),
      ],
    })
    const api = createApi(snapshot)
    installApi(api)
    const wrapper = mount(OnboardingGate, {
      global,
      slots: { default: '<div class="application">app</div>' },
    })
    await flushPromises()

    const settingsButton = wrapper.findAll('button').find(button => button.text().includes('打开模型与语音设置'))
    expect(settingsButton).toBeDefined()
    await settingsButton!.trigger('click')
    await flushPromises()

    expect(api.runRepair).toHaveBeenCalledWith({ actionId: 'navigate:settings' })
    expect(wrapper.find('.application').exists()).toBe(true)
  })

  it('keeps long backend errors in an alert region and exposes compact responsive structure', async () => {
    await setLocale('en-US', { persistSettings: false })
    const longError = 'Connection failed: '.repeat(35)
    installApi(createApi(createSnapshot({ probes: [
      probe('host.runtime', 'ready'),
      probe('backend.service', 'failed', { message: longError }),
      probe('llm.provider', 'needs_user'),
      probe('llm.model_chat', 'needs_user'),
    ] })))
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    expect(wrapper.text()).toContain(longError.slice(0, 500))
    expect(wrapper.text()).not.toContain(longError)
    expect(wrapper.find('.onboarding-page').exists()).toBe(true)
    expect(wrapper.find('.readiness-rail').exists()).toBe(true)
    expect(wrapper.find('[aria-live="polite"]').exists()).toBe(true)
  })

  it('checks microphone and speaker only after explicit button activation', async () => {
    const ready = createSnapshot({
      state: 'ready',
      readyForText: true,
      probes: [
        probe('host.runtime', 'ready'),
        probe('backend.service', 'ready'),
        probe('llm.provider', 'ready'),
        probe('llm.model_chat', 'ready'),
        probe('host.microphone', 'needs_user', { requiredForText: false }),
        probe('host.speaker', 'needs_user', { requiredForText: false }),
      ],
    })
    const api = createApi(ready)
    installApi(api)
    const stopTrack = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    const oscillatorStart = vi.fn()
    const contextClose = vi.fn().mockResolvedValue(undefined)
    class AudioContextMock {
      currentTime = 0
      destination = {}
      state: AudioContextState = 'running'
      resume = vi.fn().mockResolvedValue(undefined)
      close = contextClose
      createGain = () => ({ gain: { value: 0 }, connect: vi.fn() })
      createOscillator = () => ({
        frequency: { value: 0 },
        connect: vi.fn(),
        onended: null as (() => void) | null,
        start: oscillatorStart,
        stop() { queueMicrotask(() => this.onended?.()) },
      })
    }
    vi.stubGlobal('AudioContext', AudioContextMock)

    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(oscillatorStart).not.toHaveBeenCalled()

    await wrapper.findAll('button').find(button => button.text().includes('检查麦克风'))!.trigger('click')
    await flushPromises()
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(stopTrack).toHaveBeenCalledTimes(1)
    expect(api.reportDeviceProbe).toHaveBeenCalledWith({
      probeId: 'host.microphone',
      outcome: 'ready',
      messageCode: 'permission_granted',
    })

    await wrapper.findAll('button').find(button => button.text().includes('检查扬声器'))!.trigger('click')
    await flushPromises()
    expect(oscillatorStart).toHaveBeenCalledTimes(1)
    expect(contextClose).toHaveBeenCalledTimes(1)
    expect(api.reportDeviceProbe).toHaveBeenCalledWith({
      probeId: 'host.speaker',
      outcome: 'ready',
      messageCode: 'test_completed',
    })
    expect(wrapper.text()).toContain('测试音已播放')
  })

  it('maps denied microphone permission to the closed device outcome', async () => {
    const ready = createSnapshot({ state: 'ready', readyForText: true })
    const api = createApi(ready)
    installApi(api)
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError'))
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    const wrapper = mount(OnboardingGate, { global })
    await flushPromises()

    await wrapper.findAll('button').find(button => button.text().includes('检查麦克风'))!.trigger('click')
    await flushPromises()

    expect(api.reportDeviceProbe).toHaveBeenCalledWith({
      probeId: 'host.microphone',
      outcome: 'unavailable',
      messageCode: 'permission_denied',
    })
    expect(wrapper.text()).toContain('麦克风检查失败')
  })
})

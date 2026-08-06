import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import OverviewPanel from '../domains/system/views/OverviewPanel.vue'
import { useSystemStore } from '../stores/systemStore'

const clientMocks = vi.hoisted(() => ({
  getGovernanceReport: vi.fn(),
  getSessions: vi.fn(),
  getSummary: vi.fn(),
  getReadiness: vi.fn(),
  rewriteSummary: vi.fn(),
  settingsLoad: vi.fn(),
  companionRuntime: vi.fn(),
  heartbeat: vi.fn(),
  petState: vi.fn(),
  petCatalog: vi.fn(),
}))

vi.mock('../api/client', () => ({
  summaryClient: {
    getGovernanceReport: clientMocks.getGovernanceReport,
    getSessions: clientMocks.getSessions,
    getSummary: clientMocks.getSummary,
    getReadiness: clientMocks.getReadiness,
    rewriteSummary: clientMocks.rewriteSummary,
  },
  systemClient: {
    companionRuntime: clientMocks.companionRuntime,
    heartbeat: clientMocks.heartbeat,
  },
  settingsClient: {
    load: clientMocks.settingsLoad,
    save: vi.fn(),
  },
}))

vi.mock('../api/clients/summary-client', () => ({
  summaryClient: {
    getGovernanceReport: clientMocks.getGovernanceReport,
    exportGovernanceReport: vi.fn(),
  },
}))

vi.mock('@/utils/petControl', () => ({
  petControl: {
    getState: clientMocks.petState,
    getCatalog: clientMocks.petCatalog,
    setModel: vi.fn(),
    setScale: vi.fn(),
    setOpacity: vi.fn(),
    setVisible: vi.fn(),
    setDoNotDisturb: vi.fn(),
    setInteractMode: vi.fn(),
    setClickThrough: vi.fn(),
    setLocked: vi.fn(),
    snapBottomRight: vi.fn(),
    reloadRenderer: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('../stores/companionStore', () => ({
  useCompanionStore: () => ({
    activeCompanionId: 'default',
    activeCompanion: null,
    companions: [],
    loadCompanions: vi.fn(),
  }),
}))

const global = {
  stubs: {
    PanelShell: {
      props: ['title'],
      template: '<section><h1>{{ title }}</h1><slot /></section>',
    },
    AsyncState: {
      template: '<div><slot /></div>',
    },
    'el-button': {
      props: ['loading', 'disabled'],
      template: '<button :disabled="disabled"><slot /></button>',
    },
    'el-empty': {
      props: ['description'],
      template: '<div>{{ description }}</div>',
    },
    'el-select': {
      template: '<select><slot /></select>',
    },
    'el-option': {
      template: '<option><slot /></option>',
    },
    'el-tag': {
      template: '<span><slot /></span>',
    },
    'el-slider': {
      template: '<input />',
    },
    'el-switch': {
      template: '<input />',
    },
  },
}

describe('OverviewPanel chain self check', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    window.localStorage.clear()
    setActivePinia(createPinia())

    clientMocks.settingsLoad.mockResolvedValue({
      llm: {
        provider: 'custom',
        base_url: 'https://api.example/v1',
        api_key: '',
        model: '',
        temperature: 1,
        top_p: 1,
      },
      tts: {
        provider: 'genie-tts',
      },
      asr: {
        provider: 'sensevoice-service',
        base_url: '',
        api_key: '',
      },
      svc: {},
      summary: {},
      system: { language: 'zh', theme: 'light' },
    })
    clientMocks.getSessions.mockResolvedValue({ sessions: [] })
    clientMocks.getGovernanceReport.mockResolvedValue({ trends: [], alerts: [], summary: {} })
    clientMocks.getReadiness.mockResolvedValue({
      ready: false,
      checks: {
        llm: { ok: false, message: 'LLM 未配置' },
        tts: { ok: true },
        database: { ok: true },
      },
    })
    clientMocks.companionRuntime.mockResolvedValue({
      heartbeat: { persona: null, behavior_events: [] },
    })
    clientMocks.petState.mockResolvedValue({
      modelType: 'live2d',
      modelId: null,
      displayId: null,
      scale: 0.28,
      positionX: null,
      positionY: null,
      placement: 'bottom-right',
      visible: true,
      doNotDisturb: false,
      interactMode: false,
      clickThrough: true,
      locked: false,
      opacity: 1,
      ready: false,
    })
    clientMocks.petCatalog.mockResolvedValue({ activeModelId: null, models: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders compact blocking issues for the conversation, voice, and pet chain', async () => {
    const wrapper = mount(OverviewPanel, { global })
    const systemStore = useSystemStore()
    systemStore.controlRunning = true
    systemStore.pythonRunning = false
    systemStore.sioConnected = false

    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('.chain-check')).toHaveLength(7)
    expect(wrapper.find('.chain-issues').exists()).toBe(true)
    expect(wrapper.text()).toContain('Python 后端未连接')
    expect(wrapper.text()).toContain('Socket.IO 未连接')
    expect(wrapper.text()).toContain('LLM 未选择模型')
    expect(wrapper.text()).toContain('ASR 缺少地址')
    expect(wrapper.text()).toContain('桌宠模型未加载')
    expect(clientMocks.companionRuntime).not.toHaveBeenCalled()
  })

  it('pauses pet synchronization while hidden and refreshes once on resume', async () => {
    vi.useFakeTimers()
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    visibility.mockReturnValue('visible')
    const wrapper = mount(OverviewPanel, { global })
    await flushPromises()
    const initialCalls = clientMocks.petState.mock.calls.length
    const initialCatalogCalls = clientMocks.petCatalog.mock.calls.length

    vi.advanceTimersByTime(5_000)
    await flushPromises()
    expect(clientMocks.petState.mock.calls.length).toBe(initialCalls)

    vi.advanceTimersByTime(54_999)
    await flushPromises()
    expect(clientMocks.petState.mock.calls.length).toBe(initialCalls)
    expect(clientMocks.petCatalog.mock.calls.length).toBe(initialCatalogCalls)

    vi.advanceTimersByTime(5_000)
    await flushPromises()
    expect(clientMocks.petState.mock.calls.length).toBeGreaterThan(initialCalls)
    expect(clientMocks.petCatalog.mock.calls.length).toBe(initialCatalogCalls)

    visibility.mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    const hiddenCalls = clientMocks.petState.mock.calls.length
    vi.advanceTimersByTime(15_000)
    await flushPromises()
    expect(clientMocks.petState.mock.calls.length).toBe(hiddenCalls)

    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(clientMocks.petState.mock.calls.length).toBeGreaterThan(hiddenCalls)
    wrapper.unmount()
    visibility.mockRestore()
  })
})

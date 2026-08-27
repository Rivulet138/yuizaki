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
  providers: vi.fn(),
  connectors: vi.fn(),
  platforms: vi.fn(),
  voiceDiagnostics: vi.fn(),
  petState: vi.fn(),
  petCatalog: vi.fn(),
  getAvatarCapabilities: vi.fn(),
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
    providers: clientMocks.providers,
    connectors: clientMocks.connectors,
    platforms: clientMocks.platforms,
    voiceDiagnostics: clientMocks.voiceDiagnostics,
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
    getAvatarCapabilities: clientMocks.getAvatarCapabilities,
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
      props: ['error'],
      template: '<div><span v-if="error">{{ error }}</span><slot /></div>',
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
    'el-alert': {
      props: ['title'],
      template: '<div>{{ title }}<slot /></div>',
    },
    'router-link': {
      props: ['to'],
      template: '<a :href="to"><slot /></a>',
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
    clientMocks.providers.mockResolvedValue({
      providers: [
        { id: 'llm', kind: 'llm', label: 'LLM', provider: 'custom', model: 'demo', configured: true, available: true, healthy: true, optional: false, capabilities: [], message: '', source: 'test' },
      ],
      summary: { total: 1, configured: 1, available: 1, healthy: 1, requiredHealthy: true },
    })
    clientMocks.connectors.mockResolvedValue({
      connectors: [],
      summary: { total: 0, installed: 0, enabled: 0, running: 0, failures: 0, uninstalled: 0, canDisable: 0 },
    })
    clientMocks.platforms.mockResolvedValue({ host: { system: 'test', displayServer: 'test' }, platforms: [], statusLegend: [], schemaVersion: 1, generatedAt: '' })
    clientMocks.voiceDiagnostics.mockResolvedValue({
      sample_count: 0,
      stages: {},
      comfort: {},
      evidence_kinds: [],
      evidence_claim: 'none',
      providers: {},
      capability: { voice: 'not_measured', text_chat: 'available', text_chat_blocked_by_voice: false },
      recommendations: [],
    })
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
    clientMocks.getAvatarCapabilities.mockResolvedValue({
      success: true,
      capabilities: {
        revision: 'test', modelType: 'live2d', modelId: null, generatedAt: 0,
        actions: { behavior: true, affect: false, gaze: true, motion: false, expression: false, parameterPatch: false, viseme: false, cancel: true },
        expressions: [], motions: [], parameters: [],
      },
    })
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

    expect(wrapper.findAll('.runtime-chain-item')).toHaveLength(7)
    expect(wrapper.find('.runtime-action-list').exists()).toBe(true)
    expect(wrapper.findAll('.runtime-action-item').length).toBeGreaterThanOrEqual(5)
    expect(wrapper.text()).toContain('Python 后端未连接')
    expect(wrapper.text()).toContain('Socket.IO 未连接')
    expect(wrapper.text()).toContain('LLM 未选择模型')
    expect(wrapper.text()).toContain('ASR 缺少地址')
    expect(wrapper.text()).toContain('桌宠模型未加载')
    expect(wrapper.text()).toContain('需要处理')
    expect(wrapper.text()).toContain('查看诊断')
    expect(wrapper.text()).not.toContain('运行状态清单')
    expect(wrapper.text()).toContain('语音体验')
    expect(wrapper.text()).toContain('暂无')
    expect(clientMocks.voiceDiagnostics).toHaveBeenCalled()
    expect(clientMocks.companionRuntime).not.toHaveBeenCalled()
  })

  it('renders governance request failures instead of presenting them as empty data', async () => {
    clientMocks.getGovernanceReport.mockRejectedValueOnce(new Error('治理快照不可用'))
    const wrapper = mount(OverviewPanel, { global })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('治理快照不可用')
  })

  it('shows measured voice quality separately from provider configuration', async () => {
    clientMocks.voiceDiagnostics.mockResolvedValue({
      sample_count: 12,
      stages: {
        first_audio: { p95_ms: 480 },
        interruption: { p95_ms: 190 },
      },
      comfort: {},
      evidence_kinds: ['synthetic_fixture'],
      evidence_claim: 'synthetic_comfort_regression_only',
      providers: {},
      capability: { voice: 'configured', text_chat: 'available', text_chat_blocked_by_voice: false },
      recommendations: ['首包延迟偏高'],
    })
    const wrapper = mount(OverviewPanel, { global })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('本地 fixture')
    expect(wrapper.text()).toContain('480 ms')
    expect(wrapper.text()).toContain('190 ms')
    expect(wrapper.text()).toContain('首包延迟偏高')
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

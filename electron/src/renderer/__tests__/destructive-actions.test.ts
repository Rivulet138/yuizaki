import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import DeployPanel from '../domains/deploy/views/DeployPanel.vue'
import PetControlPanel from '../domains/pet/views/PetControlPanel.vue'
import SettingsPanel from '../domains/settings/views/SettingsPanel.vue'

const petControlMocks = vi.hoisted(() => ({
  getState: vi.fn(),
  getCatalog: vi.fn(),
  getDisplays: vi.fn(),
  deleteLocalModel: vi.fn(),
  setVisible: vi.fn(),
  updateConfig: vi.fn(),
}))

const settingsDomainMocks = vi.hoisted(() => ({
  loadSettings: vi.fn(),
  patchSettings: vi.fn(),
  loadLlmModels: vi.fn(),
  testLlm: vi.fn(),
  testTts: vi.fn(),
  warmupTts: vi.fn(),
}))

const settingsClientMocks = vi.hoisted(() => ({
  adminTokenStatus: vi.fn(),
  metadata: vi.fn(),
  history: vi.fn(),
  clearHistory: vi.fn(),
  rollback: vi.fn(),
  deleteSetting: vi.fn(),
  clearAdminToken: vi.fn(),
  backendTokenStatus: vi.fn(),
  ttsStatus: vi.fn(),
}))

const resourceClientMocks = vi.hoisted(() => ({
  status: vi.fn(),
  storageStatus: vi.fn(),
  cleanupStorage: vi.fn(),
  prepareSherpaOnline: vi.fn(),
  cancel: vi.fn(),
  remove: vi.fn(),
}))

const systemClientMocks = vi.hoisted(() => ({
  pythonHealth: vi.fn(),
  startPython: vi.fn(),
  stopPython: vi.fn(),
  openExternal: vi.fn(),
}))

const summaryClientMocks = vi.hoisted(() => ({
  getReadiness: vi.fn(),
}))

const elementPlusMocks = vi.hoisted(() => ({
  error: vi.fn(),
  info: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  confirm: vi.fn(),
}))

vi.mock('@/utils/petControl', () => ({
  petControl: petControlMocks,
}))

const settingsResponse = {
  llm: {
    provider: 'custom',
    base_url: '',
    api_key: '',
    model: '',
    temperature: 0.7,
    top_p: 1,
    timeout: 60,
    context_max_tokens: 12000,
    default_max_output_tokens: 2048,
  },
  tts: {
    genie_character: 'feibi',
    genie_model_dir: '',
    base_url: '',
    lang: 'zh',
    speed: 1,
    volume: 1,
    ref_audio: '',
    ref_text: '',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: 'genie-tts',
    voice: '',
    timeout: 90,
  },
  asr: {
    provider: 'sensevoice-service',
    base_url: 'http://127.0.0.1:8899/v1',
    api_key: '',
    timeout: 60,
    sensevoice_model: 'iic/SenseVoiceSmall',
    sensevoice_device: 'cpu',
    sherpa_model_path: '',
    sherpa_tokens_path: '',
    sherpa_num_threads: 2,
    sherpa_provider: 'cpu',
    language: 'zh',
    vad_threshold: 0.5,
    vad_min_silence_ms: 500,
    asr_partial_every: 15,
  },
  svc: {
    provider: 'soulx-service',
    base_url: 'http://127.0.0.1:7861',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
  summary: {
    trigger_messages: 24,
    keep_recent_messages: 8,
    item_max_chars: 140,
    rewrite_interval_messages: 6,
    quality_scorer_mode: 'rule',
    quality_score_cooldown_seconds: 300,
    quality_score_budget_per_hour: 20,
  },
  system: {
    language: 'zh-CN',
    theme: 'light',
  },
  memory: {
    backend: 'inmemory',
    qdrant_url: 'http://127.0.0.1:6333',
    qdrant_api_key: '',
    qdrant_collection: 'memories',
    qdrant_auto_start: true,
    qdrant_docker_image: 'qdrant/qdrant:v1.18.3',
    qdrant_docker_container: 'yuizaki-qdrant',
    qdrant_docker_volume: 'yuizaki-qdrant-storage',
    embedding_model: 'Qwen/Qwen3-Embedding-0.6B',
  },
}

const settingsState = ref(settingsResponse)
const ttsStatusState = ref({
  available: true,
  loading: false,
  warmup_running: false,
  warming_up: false,
  inference_running: true,
  character: 'feibi',
  provider: 'genie-tts',
  capabilities: {
    provider: 'genie-tts',
    locality: 'local',
    input_text_streaming: false,
    output_audio_streaming: true,
    output_transport: 'pcm_s16le',
    alignment: 'viseme',
    viseme_vocabulary: ['aa', 'ih'],
    warmup: true,
    cancellation: 'cooperative',
  },
  cacheDir: '',
  configuredModelDir: '',
  last_cancel_ms: 42,
  last_load_ms: 800,
  last_load_queue_ms: 120,
  last_load_model_ms: 680,
  load_latency_summary: {
    total: { samples: 12, latest_ms: 800, p50_ms: 740, p95_ms: 910 },
    queue: { samples: 12, latest_ms: 120, p50_ms: 80, p95_ms: 150 },
    model: { samples: 12, latest_ms: 680, p50_ms: 660, p95_ms: 780 },
  },
  last_warmup_ms: 600,
  last_warmup_queue_ms: 50,
  last_warmup_inference_ms: 550,
  warmup_latency_summary: {
    total: { samples: 8, latest_ms: 600, p50_ms: 580, p95_ms: 720 },
    queue: { samples: 8, latest_ms: 50, p50_ms: 40, p95_ms: 90 },
    inference: { samples: 8, latest_ms: 550, p50_ms: 530, p95_ms: 650 },
  },
  last_ready_wait_ms: 18,
  ready_wait_latency_summary: { samples: 14, latest_ms: 18, p50_ms: 15, p95_ms: 25 },
  last_generation_ms: 320,
  generation_latency_summary: { samples: 20, latest_ms: 320, p50_ms: 280, p95_ms: 460 },
  cancel_latency_summary: { samples: 6, latest_ms: 42, p50_ms: 35, p95_ms: 60 },
  cancel_count: 1,
  last_error: '',
})
const emptyRequest = () => ({
  loading: false,
  error: '',
  reset: vi.fn(),
})

vi.mock('../domains/settings/composables/useSettingsDomain', () => ({
  useSettingsDomain: () => ({
    settings: settingsState,
    settingsRequest: emptyRequest(),
    updateRequest: emptyRequest(),
    llmModels: ref([]),
    llmModelsRequest: emptyRequest(),
    testLlmRequest: emptyRequest(),
    testTtsRequest: emptyRequest(),
    warmupTtsRequest: emptyRequest(),
    ttsStatus: ttsStatusState,
    ttsStatusRequest: emptyRequest(),
    loadSettings: settingsDomainMocks.loadSettings,
    patchSettings: settingsDomainMocks.patchSettings,
    loadLlmModels: settingsDomainMocks.loadLlmModels,
    testLlm: settingsDomainMocks.testLlm,
    testTts: settingsDomainMocks.testTts,
    warmupTts: settingsDomainMocks.warmupTts,
    loadTtsStatus: settingsClientMocks.ttsStatus,
  }),
}))

vi.mock('@/state/settingsStore', () => ({
  useSettingsStore: () => ({
    state: {
      system: { language: 'zh-CN', theme: 'light' },
    },
    saveSettings: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/api/clients/settings-client', () => ({
  settingsClient: settingsClientMocks,
}))

vi.mock('@/api/clients/resource-client', () => ({
  resourceClient: resourceClientMocks,
}))

vi.mock('@/api/client', () => ({
  systemClient: systemClientMocks,
  summaryClient: summaryClientMocks,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: elementPlusMocks.error,
    info: elementPlusMocks.info,
    success: elementPlusMocks.success,
    warning: elementPlusMocks.warning,
  },
  ElMessageBox: {
    confirm: elementPlusMocks.confirm,
  },
}))

const ElementInputStub = defineComponent({
  props: {
    modelValue: {
      type: [String, Number],
      default: '',
    },
    placeholder: {
      type: String,
      default: '',
    },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit }) {
    return () => h('input', {
      placeholder: props.placeholder,
      value: String(props.modelValue ?? ''),
      onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
      onChange: (event: Event) => emit('change', (event.target as HTMLInputElement).value),
    })
  },
})

const global = {
  stubs: {
    AsyncState: { template: '<div><slot /></div>' },
    Connection: true,
    Document: true,
    Download: true,
    PanelShell: { template: '<section><slot name="actions" /><slot /></section>' },
    Refresh: true,
    Upload: true,
    'el-alert': { props: ['title', 'description'], template: '<div>{{ title }} {{ description }}</div>' },
    'el-button': {
      props: ['disabled', 'loading'],
      emits: ['click'],
      template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
    },
    'el-card': { template: '<section><slot name="header" /><slot /></section>' },
    'el-collapse': { template: '<section><slot /></section>' },
    'el-collapse-item': { template: '<section><slot /></section>' },
    'el-empty': { template: '<div />' },
    'el-form': { template: '<form><slot /></form>' },
    'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
    'el-icon': { template: '<i><slot /></i>' },
    'el-input': ElementInputStub,
    'el-input-number': ElementInputStub,
    'el-option': { template: '<option><slot /></option>' },
    'el-radio-button': { template: '<button><slot /></button>' },
    'el-radio-group': { template: '<div><slot /></div>' },
    'el-segmented': { template: '<div />' },
    'el-select': { template: '<select><slot /></select>' },
    'el-slider': { template: '<input />' },
    'el-switch': { template: '<input />' },
    'el-tab-pane': { template: '<section><slot /></section>' },
    'el-table': { template: '<table><slot /></table>' },
    'el-table-column': { template: '<td><slot /></td>' },
    'el-tabs': { template: '<section><slot /></section>' },
    'el-tag': { template: '<span><slot /></span>' },
  },
}

describe('destructive action confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    elementPlusMocks.confirm.mockRejectedValue(new Error('cancel'))
    petControlMocks.getState.mockResolvedValue({
      modelType: 'live2d',
      modelId: 'local:hiyori',
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
      lipSyncProfile: {
        gain: 4.2,
        noiseGate: 0.008,
        maxOpen: 1,
        attack: 0.42,
        release: 0.22,
      },
      ready: true,
    })
    petControlMocks.getCatalog.mockResolvedValue({
      activeModelId: 'local:hiyori',
      models: [{
        id: 'local:hiyori',
        name: 'Hiyori Local',
        type: 'live2d',
        source: 'local',
        assetPath: 'C:/models/hiyori',
        motions: [],
        expressions: [],
        emotions: [],
        promptContext: '',
      }],
    })
    petControlMocks.getDisplays.mockResolvedValue({
      activeDisplayId: null,
      displays: [],
    })
    petControlMocks.setVisible.mockResolvedValue({ success: true, visible: false })
    petControlMocks.updateConfig.mockResolvedValue({
      modelType: 'live2d',
      modelId: 'local:hiyori',
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
      lipSyncProfile: {
        gain: 4.2,
        noiseGate: 0.008,
        maxOpen: 1,
        attack: 0.42,
        release: 0.22,
      },
      ready: true,
    })
    settingsClientMocks.adminTokenStatus.mockResolvedValue({ hasToken: true })
    settingsClientMocks.backendTokenStatus.mockResolvedValue({ hasToken: true, source: 'environment', requiresRestart: false })
    settingsClientMocks.ttsStatus.mockResolvedValue(ttsStatusState.value)
    settingsDomainMocks.warmupTts.mockResolvedValue({ ok: true, queued: true, runtime: ttsStatusState.value })
    settingsDomainMocks.patchSettings.mockResolvedValue({ runtime_applied: [], runtime_changed: [] })
    settingsClientMocks.metadata.mockResolvedValue({})
    settingsClientMocks.history.mockResolvedValue({ history: [], count: 0 })
    resourceClientMocks.status.mockResolvedValue(null)
    resourceClientMocks.storageStatus.mockResolvedValue({ categories: [], total_bytes: 0, reclaimable_bytes: 0 })
    resourceClientMocks.cleanupStorage.mockResolvedValue({
      deleted_files: 0,
      failed_files: 0,
      reclaimed_bytes: 0,
      completed: [],
      status: { categories: [], total_bytes: 0, reclaimable_bytes: 0 },
    })
    resourceClientMocks.cancel.mockResolvedValue({ success: true, cancelled: [], status: null })
    resourceClientMocks.remove.mockResolvedValue({
      success: true,
      message: 'removed',
      removed: ['sherpa_online'],
      failed: [],
      reclaimedBytes: 1024,
      status: null,
    })
    systemClientMocks.pythonHealth.mockResolvedValue({ status: 'ok', healthy: true })
    systemClientMocks.startPython.mockResolvedValue({ success: true })
    systemClientMocks.stopPython.mockResolvedValue({ success: true })
    systemClientMocks.openExternal.mockResolvedValue(undefined)
    summaryClientMocks.getReadiness.mockResolvedValue({ ready: true, checks: {} })
    Object.defineProperty(window, 'petApi', {
      value: {
        python: {
          health: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        },
      },
      configurable: true,
    })
  })

  it('does not delete a local pet model when confirmation is cancelled', async () => {
    const wrapper = mount(PetControlPanel, { global })
    await flushPromises()

    const deleteButton = wrapper.findAll('button').find((button) => button.text().includes('删除本地模型'))
    expect(deleteButton).toBeTruthy()
    await deleteButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('Hiyori Local'),
      '删除本地模型',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(petControlMocks.deleteLocalModel).not.toHaveBeenCalled()
  })

  it('refreshes pet panel state after hiding the desktop pet', async () => {
    const wrapper = mount(PetControlPanel, { global })
    await flushPromises()
    expect(petControlMocks.getState).toHaveBeenCalledTimes(1)

    const hideButton = wrapper.findAll('button').find((button) => button.text().includes('隐藏桌宠') || button.text().includes('闅愯棌妗屽疇'))
    expect(hideButton).toBeTruthy()
    await hideButton?.trigger('click')
    await flushPromises()

    expect(petControlMocks.setVisible).toHaveBeenCalledWith(false)
    expect(petControlMocks.getState).toHaveBeenCalledTimes(2)
  })

  it('submits all lip-sync calibration fields from the pet panel', async () => {
    const wrapper = mount(PetControlPanel, { global })
    await flushPromises()

    const advancedControls = wrapper.get('details.pet-advanced-controls')
    expect(advancedControls.get('summary').exists()).toBe(true)
    const card = advancedControls.find('.lipsync-card')
    expect(card.exists()).toBe(true)
    expect(advancedControls.find('.expression-card').exists()).toBe(true)
    const applyButton = card.findAll('button').find((button) => button.text().includes('应用'))
    expect(applyButton).toBeTruthy()
    await applyButton?.trigger('click')
    await flushPromises()

    expect(petControlMocks.updateConfig).toHaveBeenCalledWith({
      lipSyncProfile: {
        gain: 4.2,
        noiseGate: 0.008,
        maxOpen: 1,
        attack: 0.42,
        release: 0.22,
      },
    })
  })

  it('does not stop the backend when confirmation is cancelled', async () => {
    const wrapper = mount(DeployPanel, { global })
    await flushPromises()

    const stopButton = wrapper.findAll('button').find((button) => button.text().includes('停止后端'))
    expect(stopButton).toBeTruthy()
    await stopButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('中断当前对话'),
      '停止后端',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(systemClientMocks.stopPython).not.toHaveBeenCalled()
  })

  it('disables API docs while the backend is offline', async () => {
    systemClientMocks.pythonHealth.mockRejectedValue(new Error('offline'))
    const wrapper = mount(DeployPanel, { global })
    await flushPromises()

    const docsButton = wrapper.findAll('button').find((button) => button.text().includes('API 文档'))
    expect(docsButton).toBeTruthy()
    expect(docsButton?.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('刷新运行状态')
    expect(systemClientMocks.openExternal).not.toHaveBeenCalled()
  })

  it('does not clear settings history when confirmation is cancelled', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    const clearButton = wrapper.findAll('button').find((button) => button.text().includes('清空历史'))
    expect(clearButton).toBeTruthy()
    await clearButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.any(String),
      '清空设置历史',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(settingsClientMocks.clearHistory).not.toHaveBeenCalled()
  })

  it('shows provider status in the model list and the Genie TTS form', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    expect(wrapper.text()).toMatch(/Ollama\s*待选模型/)
    expect(wrapper.text()).toMatch(/LM Studio\s*待选模型/)
    expect(wrapper.text()).toMatch(/自定义\s*未配置/)
    expect(wrapper.text()).toContain('Genie 角色')
    expect(wrapper.text()).not.toContain('仅使用本地 Genie TTS 链路')
    expect(wrapper.text()).not.toContain('Edge TTS')
    expect(wrapper.text()).toContain('Genie TTS')
    expect(wrapper.text()).toContain('\u7a33\u5b9a\u53e5\u6bb5')
    expect(wrapper.text()).toContain('Viseme')
    expect(wrapper.text()).toContain('合成中')
    expect(wrapper.text()).toContain('上次打断收尾')
    expect(wrapper.text()).toContain('P50 740ms · P95 910ms · n=12')
    expect(wrapper.text()).toContain('P50 580ms · P95 720ms · n=8')
    expect(wrapper.text()).toContain('P50 15ms · P95 25ms · n=14')
    expect(wrapper.text()).toContain('P50 280ms · P95 460ms · n=20')
    expect(wrapper.text()).toContain('P50 35ms · P95 60ms · n=6')
    expect(wrapper.text()).toContain('识别语言提示')
    expect(wrapper.text()).toContain('端点静音上限：500ms')
    expect(wrapper.text()).not.toContain('224–352ms')
    expect(wrapper.text()).not.toContain('按住说话与全局快捷键')
    expect(wrapper.text()).not.toContain('允许拖动、缩放和直接操作桌宠')
    expect(wrapper.text()).not.toContain('Whisper 模型')
    expect(wrapper.text()).not.toContain('计算精度')
  })

  it('renders verified streaming ASR resources and uses the dedicated install action', async () => {
    const summary = {
      ready: true,
      state: 'ready',
      message: 'Ready',
      details: [],
      metadata: {
        label: 'Sherpa Streaming Zipformer2 CTC',
        version: '2025-04-01',
        license: 'Apache-2.0',
        licenseUrl: 'https://example.invalid/license',
        downloadBytes: 1024,
        source: 'https://example.invalid/model',
        integrity: 'verified',
        inUseBy: ['流式语音识别'],
      },
    }
    const status = {
      modelRoots: { live2d: 'C:/models/live2d', vrm: 'C:/models/vrm' },
      localCounts: { live2d: 1, vrm: 0 },
      soulx: {
        ...summary,
        serviceDir: '',
        launcherPath: '',
        checkpointPath: null,
        checkpointCandidates: [],
        preprocessDir: '',
        referenceDir: '',
        hasReferenceAudio: true,
      },
      sherpa: {
        ...summary,
        assetUrl: 'https://example.invalid/offline.tar.bz2',
        modelPath: 'C:/models/sensevoice/model.int8.onnx',
        tokensPath: 'C:/models/sensevoice/tokens.txt',
        format: 'sensevoice-offline',
        validated: false,
        validationPath: null,
      },
      sherpaOnline: {
        ...summary,
        assetUrl: 'https://example.invalid/online.tar.bz2',
        modelPath: 'C:/models/streaming/model.int8.onnx',
        tokensPath: 'C:/models/streaming/tokens.txt',
        format: 'zipformer2-ctc-online',
        validated: true,
        validationPath: 'C:/models/streaming/.yuizaki-validation.json',
      },
      embedding: { ...summary, modelName: 'embedding', cachePath: null, cacheRoot: '' },
      tts: { ...summary, character: 'feibi', cacheDir: '', modelDir: '' },
      resumableDownloads: [{
        resourceId: 'sherpa',
        bytesDownloaded: 256,
        bytesTotal: 1024,
        percent: 25,
        updatedAt: '2026-07-20T00:00:00.000Z',
      }],
    }
    resourceClientMocks.status.mockResolvedValue(status)
    resourceClientMocks.prepareSherpaOnline.mockResolvedValue({ success: true, message: 'ready', status })

    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    expect(wrapper.text()).toContain('Sherpa Streaming Zipformer2 CTC')
    expect(wrapper.text()).toContain('Zipformer2 CTC verified')
    expect(wrapper.text()).toContain('C:/models/streaming/model.int8.onnx')
    expect(wrapper.text()).toContain('可续传 256 B / 1.0 KiB')

    const installButton = wrapper.findAll('button').find((button) => button.text().includes('(Streaming)'))
    expect(installButton).toBeTruthy()
    await installButton?.trigger('click')
    await flushPromises()

    expect(resourceClientMocks.prepareSherpaOnline).toHaveBeenCalledTimes(1)

    let finishPendingDownload: (() => void) | undefined
    resourceClientMocks.prepareSherpaOnline.mockImplementationOnce(() => new Promise((resolve) => {
      finishPendingDownload = () => resolve({ success: true, message: 'ready', status })
    }))
    await installButton?.trigger('click')
    await nextTick()

    const cancelDownloadButton = wrapper.findAll('button').find((button) => button.text().includes('取消下载'))
    expect(cancelDownloadButton).toBeTruthy()
    await cancelDownloadButton?.trigger('click')
    await flushPromises()

    expect(resourceClientMocks.cancel).toHaveBeenCalledWith(['sherpa_online'])
    finishPendingDownload?.()
    await flushPromises()

    elementPlusMocks.confirm.mockResolvedValueOnce('confirm')
    const removeButton = wrapper.findAll('button').find((button) => button.text().includes('永久卸载'))
    expect(removeButton).toBeTruthy()
    await removeButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('使用中'),
      '永久卸载模型',
      expect.objectContaining({ confirmButtonText: '永久卸载' }),
    )
    expect(resourceClientMocks.remove).toHaveBeenCalledWith(['sherpa_online'])
    wrapper.unmount()

    resourceClientMocks.status.mockResolvedValue({
      ...status,
      activeDownloads: [{
        resourceId: 'sherpa_online',
        phase: 'downloading',
        message: 'Downloading model archive',
        bytesDownloaded: 512,
        bytesTotal: 1024,
        percent: 50,
        startedAt: '2026-07-20T00:00:00.000Z',
        updatedAt: '2026-07-20T00:00:01.000Z',
      }],
    })
    const resumedWrapper = mount(SettingsPanel, { global })
    await flushPromises()

    expect(resumedWrapper.text()).toContain('流式语音识别')
    expect(resumedWrapper.text()).toContain('512 B / 1.0 KiB')
    const resumedCancelButton = resumedWrapper.findAll('button').find((button) => button.text().includes('取消下载'))
    expect(resumedCancelButton).toBeTruthy()
    await resumedCancelButton?.trigger('click')
    await flushPromises()
    expect(resourceClientMocks.cancel).toHaveBeenLastCalledWith(['sherpa_online'])
    resumedWrapper.unmount()
  })

  it('flushes pending settings autosave before unmount', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    const baseUrlInput = wrapper.find('input[name="llm-base-url"]')
    if (!baseUrlInput.exists()) throw new Error('LLM base URL input not found')
    await baseUrlInput.setValue('http://127.0.0.1:1234/v1')
    await baseUrlInput.trigger('change')

    expect(settingsDomainMocks.patchSettings).not.toHaveBeenCalled()
    wrapper.unmount()
    await flushPromises()

    expect(settingsDomainMocks.patchSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        llm: expect.objectContaining({
          base_url: 'http://127.0.0.1:1234/v1',
        }),
      }),
    )
  })

  it('does not reset the current provider profile when confirmation is cancelled', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    const resetButton = wrapper.findAll('button').find((button) => button.text().includes('重置当前提供商'))
    expect(resetButton).toBeTruthy()
    await resetButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('自定义'),
      '重置当前提供商',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(settingsDomainMocks.patchSettings).not.toHaveBeenCalled()
  })

  it('does not rollback settings when confirmation is cancelled', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    const rollbackButton = wrapper.findAll('button').find((button) => button.text() === '回滚')
    expect(rollbackButton).toBeTruthy()
    await rollbackButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('1'),
      '回滚设置',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(settingsClientMocks.rollback).not.toHaveBeenCalled()
  })

  it('does not delete a setting key when confirmation is cancelled', async () => {
    const wrapper = mount(SettingsPanel, { global })
    await flushPromises()

    const deleteKeyInput = wrapper.find('input[placeholder="llm.model / tts.lang"]')
    await deleteKeyInput.setValue('llm.model')
    const deleteButton = wrapper.findAll('button').find((button) => button.text() === '删除')
    expect(deleteButton).toBeTruthy()
    await deleteButton?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.confirm).toHaveBeenCalledWith(
      expect.stringContaining('llm.model'),
      '删除设置键',
      expect.objectContaining({ type: 'warning' }),
    )
    expect(settingsClientMocks.deleteSetting).not.toHaveBeenCalled()
  })
})

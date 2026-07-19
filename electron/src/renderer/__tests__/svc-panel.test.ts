import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import SVCPanel from '../domains/tools/views/SVCPanel.vue'

const settingsClientMocks = vi.hoisted(() => ({
  load: vi.fn(),
  save: vi.fn(),
  testTts: vi.fn(),
}))

const httpClientMocks = vi.hoisted(() => ({
  requestJson: vi.fn(),
  resolveBackendUrl: vi.fn(),
}))

const elementPlusMocks = vi.hoisted(() => ({
  warning: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}))

vi.mock('@/api/clients/settings-client', () => ({
  settingsClient: settingsClientMocks,
}))

vi.mock('@/api/clients/http-client', () => ({
  API_ORIGIN: 'http://localhost:8001',
  requestJson: httpClientMocks.requestJson,
  resolveBackendUrl: httpClientMocks.resolveBackendUrl,
}))

vi.mock('element-plus', () => ({
  ElMessage: elementPlusMocks,
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

const baseSettings = {
  tts: {
    genie_character: '',
    genie_model_dir: '',
    lang: 'zh',
    ref_audio: '',
    ref_text: '',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: 'genie-tts',
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
  summary: {},
  system: { language: 'zh-CN', theme: 'light' },
  llm: { provider: 'custom', base_url: '', api_key: '', model: '', temperature: 0.7, top_p: 1 },
}

const mountPanel = () => mount(SVCPanel, {
  global: {
    stubs: {
      PanelShell: { template: '<section><slot /></section>' },
      UploadFilled: true,
      'el-alert': {
        props: ['title', 'description'],
        template: '<div>{{ title }} {{ description }}</div>',
      },
      'el-button': {
        props: ['disabled', 'loading'],
        emits: ['click'],
        template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
      },
      'el-card': { template: '<section><slot name="header" /><slot /></section>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-form-item': { template: '<label><slot /></label>' },
      'el-icon': { template: '<i><slot /></i>' },
      'el-input': ElementInputStub,
      'el-input-number': ElementInputStub,
      'el-option': { template: '<option><slot /></option>' },
      'el-select': { template: '<select><slot /></select>' },
      'el-slider': { template: '<input />' },
      'el-tag': { template: '<span><slot /></span>' },
      'el-upload': defineComponent({
        props: {
          onChange: {
            type: Function,
            required: false,
          },
        },
        setup(props, { slots }) {
          const fakeAudioFile = Object.assign(new Blob(['audio'], { type: 'audio/wav' }), {
            name: 'voice.wav',
          })
          return () => h('div', [
            h('button', {
              class: 'fake-upload',
              onClick: () => props.onChange?.({ raw: fakeAudioFile }),
            }, 'upload'),
            slots.default?.(),
            slots.tip?.(),
          ])
        },
      }),
    },
  },
})

describe('SVCPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    settingsClientMocks.save.mockResolvedValue({ status: 'ok', runtime_applied: [] })
    settingsClientMocks.testTts.mockResolvedValue({ ok: true, message: 'ok' })
    httpClientMocks.requestJson.mockResolvedValue({ status: 'ok', audio_url: '/outputs/svc.wav' })
    httpClientMocks.resolveBackendUrl.mockResolvedValue('http://localhost:8001/outputs/svc.wav')
  })

  it('does not call conversion when SVC is disabled', async () => {
    settingsClientMocks.load.mockResolvedValue({
      ...baseSettings,
      svc: { ...baseSettings.svc, provider: 'disabled' },
    })

    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('.fake-upload').trigger('click')
    const button = wrapper.findAll('button').find((item) => item.text().includes('开始 SVC 转换'))
    expect(button?.attributes('disabled')).toBeDefined()
    await button?.trigger('click')

    expect(wrapper.text()).toContain('SVC 已禁用，请先在提供方中启用服务。')
    expect(httpClientMocks.requestJson).not.toHaveBeenCalled()
  })

  it('does not call conversion when SVC endpoint is empty', async () => {
    settingsClientMocks.load.mockResolvedValue({
      ...baseSettings,
      svc: { ...baseSettings.svc, base_url: '   ' },
    })

    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('.fake-upload').trigger('click')
    const button = wrapper.findAll('button').find((item) => item.text().includes('开始 SVC 转换'))
    expect(button?.attributes('disabled')).toBeDefined()
    await button?.trigger('click')

    expect(wrapper.text()).toContain('请先填写 SVC 基础 URL，再开始转换。')
    expect(httpClientMocks.requestJson).not.toHaveBeenCalled()
  })

  it('calls conversion only after audio and SVC endpoint are ready', async () => {
    settingsClientMocks.load.mockResolvedValue(baseSettings)

    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('.fake-upload').trigger('click')
    const button = wrapper.findAll('button').find((item) => item.text().includes('开始 SVC 转换'))
    expect(button?.attributes('disabled')).toBeUndefined()
    await button?.trigger('click')
    await flushPromises()

    expect(httpClientMocks.requestJson).toHaveBeenCalledWith(
      'http://localhost:8001/svc/convert',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      }),
    )
    expect(wrapper.text()).toContain('转换完成')
  })

  it('flushes pending Genie character settings before unmount', async () => {
    settingsClientMocks.load.mockResolvedValue(baseSettings)

    const wrapper = mountPanel()
    await flushPromises()
    const characterInput = wrapper.find('input[aria-label="Genie 角色"]')
    expect(characterInput.exists()).toBe(true)
    await characterInput.setValue('feibi')

    expect(settingsClientMocks.save).not.toHaveBeenCalled()
    wrapper.unmount()
    await flushPromises()

    expect(settingsClientMocks.save).toHaveBeenCalledWith({
      tts: {
        genie_character: 'feibi',
      },
    })
  })

  it('shows active ASR controls without legacy Whisper settings', async () => {
    settingsClientMocks.load.mockResolvedValue(baseSettings)

    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('select[aria-label="ASR 提供方"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Whisper 模型')
    expect(wrapper.text()).not.toContain('计算精度')
  })

  it('reports a failed TTS connection instead of showing a false success', async () => {
    settingsClientMocks.load.mockResolvedValue(baseSettings)
    settingsClientMocks.testTts.mockResolvedValue({ ok: false, message: 'TTS client not initialized' })

    const wrapper = mountPanel()
    await flushPromises()
    const button = wrapper.findAll('button').find((item) => item.text().includes('测试 TTS'))
    expect(button).toBeDefined()
    await button?.trigger('click')
    await flushPromises()

    expect(elementPlusMocks.error).toHaveBeenCalledWith('TTS client not initialized')
    expect(elementPlusMocks.success).not.toHaveBeenCalled()
  })
})

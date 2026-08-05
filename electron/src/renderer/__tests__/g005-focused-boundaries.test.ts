import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import ChatComposerStatusLine from '../domains/chat/components/ChatComposerStatusLine.vue'
import ChatVoiceStatus from '../domains/chat/components/ChatVoiceStatus.vue'
import SettingsAsrSection from '../domains/settings/components/SettingsAsrSection.vue'
import SettingsSectionHeader from '../domains/settings/components/SettingsSectionHeader.vue'
import { syncLocaleFromSettings } from '../i18n'

const voiceStubs = {
  'el-icon': { template: '<i><slot /></i>' },
  'el-segmented': {
    props: ['modelValue', 'options'],
    emits: ['change'],
    template: '<button class="segmented" type="button" @click="$emit(\'change\', options[1].value)">{{ modelValue }}</button>',
  },
}

const asrSettings = {
  provider: 'sherpa-onnx-online',
  base_url: 'http://127.0.0.1:10095',
  api_key: '',
  timeout: 60,
  sensevoice_model: 'iic/SenseVoiceSmall',
  sensevoice_device: 'cpu',
  sherpa_model_path: './model.onnx',
  sherpa_tokens_path: './tokens.txt',
  sherpa_num_threads: 2,
  sherpa_provider: 'cpu',
  language: 'zh',
  vad_threshold: 0.5,
  vad_min_silence_ms: 480,
  asr_partial_every: 15,
}

const holdVoiceProps = {
  statusClass: 'ready',
  statusText: 'Ready',
  pipelineText: 'Voice ready',
  processingText: '',
  latencySummary: '',
  recording: false,
  meterBars: [20, 40, 60],
  levelPercent: 0,
  mode: 'hold',
  modeOptions: [
    { label: 'Toggle', value: 'toggle' },
    { label: 'Hold', value: 'hold' },
  ],
  holdActive: false,
  connected: true,
  shortcutTitle: 'Voice shortcut',
  ttsPlaying: false,
}

describe('G005 focused presentation boundaries', () => {
  afterEach(() => syncLocaleFromSettings('zh-CN'))

  it('renders composer state without owning chat side effects', () => {
    const wrapper = mount(ChatComposerStatusLine, {
      props: {
        connected: true,
        webSearchEnabled: true,
        mcpEnabled: true,
        modelLabel: 'local-model',
        petLinkEnabled: true,
        ttsEnabled: true,
        voicePermissionText: 'microphone ready',
        inputTokens: 42,
      },
    })

    expect(wrapper.text()).toContain('local-model')
    expect(wrapper.text()).toContain('MCP')
    expect(wrapper.text()).toContain('microphone ready')
    expect(wrapper.text()).toContain('42 tokens')
  })

  it('renders composer status in all supported locales without hardcoded Chinese', async () => {
    const wrapper = mount(ChatComposerStatusLine, {
      props: {
        connected: false,
        webSearchEnabled: true,
        mcpEnabled: true,
        modelLabel: 'local-model',
        petLinkEnabled: false,
        ttsEnabled: false,
        voicePermissionText: 'microphone ready',
        inputTokens: 42,
      },
    })

    syncLocaleFromSettings('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('Connecting realtime channel')
    expect(wrapper.text()).toContain('Web search')
    expect(wrapper.text()).toContain('Standalone chat')

    syncLocaleFromSettings('ja-JP')
    await nextTick()
    expect(wrapper.text()).toContain('リアルタイム接続中')
    expect(wrapper.text()).toContain('ウェブ検索')
    expect(wrapper.text()).toContain('単独チャット')

    const source = readFileSync('src/renderer/domains/chat/components/ChatComposerStatusLine.vue', 'utf8')
    expect(source).not.toMatch(/[一-龥]/u)
  })

  it('emits voice mode and control intents while respecting offline state', async () => {
    const wrapper = mount(ChatVoiceStatus, {
      props: {
        statusClass: 'offline',
        statusText: 'Offline',
        pipelineText: 'Voice unavailable',
        processingText: '',
        latencySummary: '',
        recording: false,
        meterBars: [20, 40, 60],
        levelPercent: 0,
        mode: 'toggle',
        modeOptions: [
          { label: 'Toggle', value: 'toggle' },
          { label: 'Hold', value: 'hold' },
        ],
        holdActive: false,
        connected: false,
        shortcutTitle: 'Voice shortcut',
        ttsPlaying: true,
      },
      global: { stubs: voiceStubs },
    })

    expect(wrapper.get('.hold-to-talk').attributes('disabled')).toBeDefined()
    await wrapper.get('.segmented').trigger('click')
    await wrapper.get('.voice-stop-button').trigger('click')

    expect(wrapper.emitted('update:mode')).toEqual([['hold']])
    expect(wrapper.emitted('interrupt')).toEqual([[]])
    expect(wrapper.emitted('toggle-mic')).toBeUndefined()
  })

  it.each(['pointerup', 'pointercancel'])('forwards the pointer event through %s so hold-to-talk stops and releases capture', async (endEvent) => {
    const start = vi.fn()
    const stop = vi.fn()
    const setPointerCapture = vi.fn()
    const releasePointerCapture = vi.fn()
    const handlePointerDown = (event: PointerEvent) => {
      ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
      start()
    }
    const handlePointerUp = (event: PointerEvent) => {
      ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)
      stop()
    }
    const wrapper = mount(ChatVoiceStatus, {
      props: {
        ...holdVoiceProps,
        onHoldPointerDown: handlePointerDown,
        onHoldPointerUp: handlePointerUp,
      },
      global: { stubs: voiceStubs },
    })
    const holdButton = wrapper.get<HTMLButtonElement>('.hold-to-talk')
    holdButton.element.setPointerCapture = setPointerCapture
    holdButton.element.releasePointerCapture = releasePointerCapture

    await holdButton.trigger('pointerdown', { pointerId: 7, pointerType: 'mouse', button: 0 })
    await holdButton.trigger(endEvent, { pointerId: 7, pointerType: 'mouse', button: 0 })

    expect(setPointerCapture).toHaveBeenCalledOnce()
    expect(start).toHaveBeenCalledOnce()
    expect(releasePointerCapture).toHaveBeenCalledOnce()
    expect(stop).toHaveBeenCalledOnce()
  })

  it('renders a settings section title, status, and actions', () => {
    const wrapper = mount(SettingsSectionHeader, {
      props: { title: 'Speech recognition' },
      slots: {
        status: '<span class="status-marker">Local</span>',
        actions: '<button type="button">Discover</button>',
      },
    })

    expect(wrapper.get('h3').text()).toBe('Speech recognition')
    expect(wrapper.get('.status-marker').text()).toBe('Local')
    expect(wrapper.get('button').text()).toBe('Discover')
  })

  it('keeps ASR provider values round-trippable through typed parent intents', async () => {
    const wrapper = mount(SettingsAsrSection, {
      props: {
        modelValue: asrSettings,
        discoveryLoading: false,
      },
      global: {
        stubs: {
          'el-icon': { template: '<i><slot /></i>' },
          'el-card': { template: '<section><slot name="header" /><slot /></section>' },
          'el-form': { template: '<form><slot /></form>' },
          'el-form-item': { template: '<label><slot /></label>' },
          'el-option': { template: '<span />' },
          'el-input': { template: '<input />' },
          'el-input-number': { template: '<input type="number" />' },
          'el-slider': { template: '<input type="range" />' },
          'el-select': {
            props: ['modelValue'],
            emits: ['change'],
            template: '<button class="provider-select" type="button" @click="$emit(\'change\', \'openai-compatible\')">{{ modelValue }}</button>',
          },
          'el-button': {
            emits: ['click'],
            template: '<button class="discover-button" type="button" @click="$emit(\'click\')"><slot /></button>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('sherpa-onnx-online')
    await wrapper.get('.provider-select').trigger('click')
    await wrapper.get('.discover-button').trigger('click')

    expect(wrapper.emitted('update-field')).toContainEqual(['provider', 'openai-compatible'])
    expect(wrapper.emitted('discover-local')).toEqual([[]])
    expect(asrSettings.provider).toBe('sherpa-onnx-online')
  })

  it('keeps focused Chat and Settings components presentation-only and parent-owned', () => {
    const chatPanel = readFileSync('src/renderer/domains/chat/views/ChatPanel.vue', 'utf8')
    const settingsPanel = readFileSync('src/renderer/domains/settings/views/SettingsPanel.vue', 'utf8')
    const focusedComponents = [
      'src/renderer/domains/chat/components/ChatComposerStatusLine.vue',
      'src/renderer/domains/chat/components/ChatVoiceStatus.vue',
      'src/renderer/domains/settings/components/SettingsAsrSection.vue',
      'src/renderer/domains/settings/components/SettingsSectionHeader.vue',
    ].map((path) => readFileSync(path, 'utf8'))

    expect(chatPanel).toContain('<ChatComposerStatusLine')
    expect(chatPanel).toContain('<ChatVoiceStatus')
    expect(settingsPanel).toContain('<SettingsAsrSection')
    expect(focusedComponents[2]).toContain('<SettingsSectionHeader')
    expect(focusedComponents.join('\n')).not.toMatch(/Client\.|fetch\(|requestJson|onMounted|watch\(/)
  })
})

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { ElInput } from 'element-plus'
import SettingsLlmCapabilityPanel from '../domains/settings/components/SettingsLlmCapabilityPanel.vue'
import SettingsLlmVisionSection from '../domains/settings/components/SettingsLlmVisionSection.vue'

const ElSwitchStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<button data-testid="vision-toggle" @click="$emit(\'change\', !modelValue)">toggle</button>',
})

const ElInputNumberNullStub = defineComponent({
  emits: ['change'],
  template: '<button data-testid="clear-timeout" @click="$emit(\'change\', null)">clear</button>',
})

describe('Settings LLM presentation sections', () => {
  it('summarizes model capabilities without owning discovery state', () => {
    const wrapper = mount(SettingsLlmCapabilityPanel, {
      props: {
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        contextMaxTokens: 128000,
        maxOutputTokens: 16384,
        visionEnabled: false,
      },
      global: {
        stubs: {
          'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })

    expect(wrapper.text()).toContain('模型能力')
    expect(wrapper.text()).toContain('视觉')
    expect(wrapper.text()).toContain('工具')
    expect(wrapper.text()).toContain('上下文窗口')
  })

  it('emits a narrow patch when independent vision is toggled', async () => {
    const wrapper = mount(SettingsLlmVisionSection, {
      props: {
        modelValue: {
          enabled: false,
          provider: 'custom',
          baseUrl: '',
          apiKey: '',
          model: '',
          timeout: 30,
          detail: 'low',
        },
        providerOptions: [{ label: '自定义', value: 'custom' }],
      },
      global: {
        stubs: {
          'el-form-item': { template: '<label><slot /></label>' },
          'el-input': true,
          'el-input-number': true,
          'el-option': true,
          'el-select': true,
          'el-switch': ElSwitchStub,
        },
      },
    })

    await wrapper.get('[data-testid="vision-toggle"]').trigger('click')
    expect(wrapper.emitted('update')).toEqual([[{ enabled: true }]])
  })

  it('emits controlled text updates while the user is typing', async () => {
    const wrapper = mount(SettingsLlmVisionSection, {
      props: {
        modelValue: {
          enabled: true,
          provider: 'ollama',
          baseUrl: 'http://localhost:11434/v1',
          apiKey: '',
          model: '',
          timeout: 30,
          detail: 'low',
        },
        providerOptions: [{ label: 'Ollama', value: 'ollama' }],
      },
      global: {
        components: { ElInput },
        stubs: {
          'el-form-item': { template: '<label><slot /></label>' },
          'el-input-number': true,
          'el-option': true,
          'el-select': true,
          'el-switch': true,
        },
      },
    })

    const modelInput = wrapper.find('input')
    ;(modelInput.element as HTMLInputElement).value = 'vision-model'
    await modelInput.trigger('input')

    expect(wrapper.emitted('update')).toContainEqual([{ model: 'vision-model' }])
  })

  it('ignores an empty vision timeout value', async () => {
    const wrapper = mount(SettingsLlmVisionSection, {
      props: {
        modelValue: {
          enabled: true,
          provider: 'ollama',
          baseUrl: 'http://localhost:11434/v1',
          apiKey: '',
          model: 'vision-model',
          timeout: 30,
          detail: 'low',
        },
        providerOptions: [{ label: 'Ollama', value: 'ollama' }],
      },
      global: {
        stubs: {
          'el-form-item': { template: '<label><slot /></label>' },
          'el-input': true,
          'el-input-number': ElInputNumberNullStub,
          'el-option': true,
          'el-select': true,
          'el-switch': true,
        },
      },
    })

    await wrapper.get('[data-testid="clear-timeout"]').trigger('click')
    expect(wrapper.emitted('update')).toBeUndefined()
  })

  it('keeps primary LLM controls touch-sized on coarse pointers', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/renderer/domains/settings/views/SettingsPanel.css'), 'utf8')
    expect(css).toContain('@media (hover: none), (pointer: coarse)')
    expect(css).toMatch(/\.llm-settings-card[\s\S]*min-height: 44px/)
  })
})

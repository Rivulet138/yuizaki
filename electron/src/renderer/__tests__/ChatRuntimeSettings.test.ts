import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatRuntimeSettings from '../domains/chat/components/ChatRuntimeSettings.vue'

const PopoverStub = defineComponent({
  template: '<div><slot name="reference" /><slot /></div>',
})

const options = {
  model: '',
  response_mode: 'balanced' as const,
  reasoning_effort: 'default' as const,
  mcp_enabled: true,
  pet_link_enabled: true,
  tts_enabled: true,
  temperature: 1,
  top_p: 0.9,
  top_k: 500,
  min_p: 0,
  frequency_penalty: 0.2,
  presence_penalty: 0,
  repetition_penalty: 1,
  max_tokens: 2048,
  translation_target: 'zh-CN',
}

describe('ChatRuntimeSettings', () => {
  it('groups model and runtime controls behind one settings action', async () => {
    const wrapper = mount(ChatRuntimeSettings, {
      props: {
        modelValue: options,
        modelOptions: ['local-model'],
        reasoningOptions: [{ label: '默认思考', value: 'default' }],
        responseModeOptions: [{ label: '均衡', value: 'balanced' }],
        maxOutputTokens: 8192,
        modelLabel: '默认模型',
        mcpSummary: 'MCP 已就绪',
        promptActive: false,
      },
      global: {
        stubs: {
          'el-popover': PopoverStub,
          'el-segmented': { template: '<div data-testid="response-mode" />' },
          'el-select': { template: '<select><slot /></select>' },
          'el-option': { template: '<option><slot /></option>' },
          'el-switch': { template: '<button class="switch" />' },
          'el-icon': { template: '<i><slot /></i>' },
          ChatAdvancedOptions: { template: '<button aria-label="参数" />' },
        },
      },
    })

    expect(wrapper.find('[aria-label="对话运行设置"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('模型')
    expect(wrapper.text()).toContain('MCP')
    expect(wrapper.text()).toContain('桌宠联动')
    expect(wrapper.find('[data-testid="response-mode"]').exists()).toBe(true)
  })
})

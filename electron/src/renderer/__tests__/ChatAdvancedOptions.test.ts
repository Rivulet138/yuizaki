import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatAdvancedOptions from '../domains/chat/components/ChatAdvancedOptions.vue'

const model = () => ({
  temperature: 1,
  top_p: 0.9,
  top_k: 500,
  min_p: 0,
  frequency_penalty: 0.2,
  presence_penalty: 0,
  repetition_penalty: 1,
  max_tokens: 2048,
  translation_target: 'zh-CN',
})

const PopoverStub = defineComponent({
  template: '<div><slot name="reference" /><slot /></div>',
})

describe('ChatAdvancedOptions', () => {
  it('keeps the advanced controls in a presentational boundary', async () => {
    const options = model()
    const wrapper = mount(ChatAdvancedOptions, {
      props: { modelValue: options, maxOutputTokens: 8192 },
      global: {
        stubs: {
          'el-popover': PopoverStub,
          'el-slider': { template: '<input data-testid="temperature" />' },
          'el-input-number': { template: '<input />' },
          'el-select': { template: '<select><slot /></select>' },
          'el-option': { template: '<option><slot /></option>' },
          'el-icon': { template: '<i><slot /></i>' },
        },
      },
    })

    expect(wrapper.text()).toContain('温度')
    expect(wrapper.text()).toContain('最大回复 tokens')
    expect(wrapper.text()).toContain('翻译目标')
    expect(wrapper.find('[aria-label="参数"]').exists()).toBe(true)
  })
})

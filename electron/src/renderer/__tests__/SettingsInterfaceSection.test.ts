import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsInterfaceSection from '../domains/settings/components/SettingsInterfaceSection.vue'

const ElSegmentedStub = defineComponent({
  inheritAttrs: false,
  props: ['modelValue'],
  emits: ['change'],
  template: '<button v-bind="$attrs" @click="$emit(\'change\', modelValue === \'light\' ? \'dark\' : \'en-US\')">{{ modelValue }}</button>',
})

describe('SettingsInterfaceSection', () => {
  it('emits theme and language choices for the parent to apply', async () => {
    const wrapper = mount(SettingsInterfaceSection, {
      props: {
        modelValue: { theme: 'light', language: 'zh-CN' },
        themeOptions: [{ label: '浅色', value: 'light' }, { label: '深色', value: 'dark' }],
        languageOptions: [{ label: '简体中文', value: 'zh-CN' }, { label: 'English', value: 'en-US' }],
      },
      global: {
        stubs: {
          'el-card': { template: '<section><slot name="header" /><slot /></section>' },
          'el-form': { template: '<form><slot /></form>' },
          'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
          'el-segmented': ElSegmentedStub,
        },
      },
    })

    await wrapper.get('[data-testid="theme-selector"]').trigger('click')
    await wrapper.get('[data-testid="language-selector"]').trigger('click')

    expect(wrapper.emitted('change-theme')).toEqual([['dark']])
    expect(wrapper.emitted('change-language')).toEqual([['en-US']])
  })
})

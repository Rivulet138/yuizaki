import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsSvcSection, { type SvcSettings } from '../domains/settings/components/SettingsSvcSection.vue'

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
})

const ElSelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<select data-testid="svc-provider" :value="modelValue" @change="$emit(\'change\', $event.target.value)"><slot /></select>',
})

const ElInputStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<input data-testid="svc-base-url" :value="modelValue" @change="$emit(\'change\', $event.target.value)">',
})

const ElInputNumberStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<input data-testid="svc-number" :value="modelValue" @change="$emit(\'change\', Number($event.target.value))">',
})

const svc = (): SvcSettings => ({
  provider: 'soulx-service',
  base_url: 'http://127.0.0.1:9880',
  speaker_id: 0,
  pitch: 0,
  timeout: 120,
})

const mountSection = (modelValue = svc()) => mount(SettingsSvcSection, {
  props: {
    modelValue,
    discoveryLoading: false,
  },
  global: {
    stubs: {
      'el-button': ElButtonStub,
      'el-card': { template: '<section><slot name="header" /><slot /></section>' },
      'el-alert': { template: '<div><slot /></div>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
      'el-icon': { template: '<i><slot /></i>' },
      'el-select': ElSelectStub,
      'el-option': { template: '<option><slot /></option>' },
      'el-input': ElInputStub,
      'el-input-number': ElInputNumberStub,
      'el-tag': { template: '<span><slot /></span>' },
      'SettingsSectionHeader': { template: '<header><slot name="status" /><slot name="actions" /></header>' },
    },
  },
})

describe('SettingsSvcSection', () => {
  it('emits discovery and field updates without owning persistence', async () => {
    const wrapper = mountSection()

    await wrapper.get('[data-testid="discover-svc"]').trigger('click')
    await wrapper.get('[data-testid="svc-provider"]').setValue('disabled')
    await wrapper.get('[data-testid="svc-base-url"]').setValue('http://localhost:9880')

    expect(wrapper.emitted('discover-local')).toEqual([[]])
    expect(wrapper.emitted('update-field')).toContainEqual(['provider', 'disabled'])
    expect(wrapper.emitted('update-field')).toContainEqual(['base_url', 'http://localhost:9880'])
  })

  it('reports configured state from provider and endpoint', async () => {
    const wrapper = mountSection()
    expect(wrapper.text()).toContain('已配置')

    await wrapper.setProps({ modelValue: { ...svc(), base_url: '' } })
    expect(wrapper.text()).toContain('可选')
  })
})

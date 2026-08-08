import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsAccessSection from '../domains/settings/components/SettingsAccessSection.vue'

const ElInputStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'keyup'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup="$emit(\'keyup\', $event)">',
})

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
})

const mountSection = () => mount(SettingsAccessSection, {
  props: {
    adminToken: '',
    adminTokenConfigured: false,
    adminTokenLoading: false,
    backendToken: '',
    backendTokenConfigured: true,
    backendTokenBusy: false,
    backendTokenStatusKnown: true,
    backendTokenSourceLabel: 'environment',
    backendTokenPreview: 'abcd…wxyz',
    backendTokenRequiresRestart: false,
  },
  global: {
    stubs: {
      'el-card': { template: '<section><slot /></section>' },
      'el-input': ElInputStub,
      'el-button': ElButtonStub,
      'el-tag': { template: '<span><slot /></span>' },
    },
  },
})

describe('SettingsAccessSection', () => {
  it('keeps token input controlled and emits commands', async () => {
    const wrapper = mountSection()
    const inputs = wrapper.findAll('input')

    await inputs[0].setValue('admin-secret')
    await inputs[0].trigger('keyup', { key: 'Enter' })
    await inputs[1].setValue('backend-secret')
    await inputs[1].trigger('keyup', { key: 'Enter' })
    await wrapper.get('[data-testid="clear-admin-token"]').trigger('click')
    await wrapper.get('[data-testid="reset-backend-token"]').trigger('click')

    expect(wrapper.emitted('update:adminToken')).toEqual([['admin-secret']])
    expect(wrapper.emitted('save-admin-token')).toEqual([[]])
    expect(wrapper.emitted('update:backendToken')).toEqual([['backend-secret']])
    expect(wrapper.emitted('save-backend-token')).toEqual([[]])
    expect(wrapper.emitted('clear-admin-token')).toEqual([[]])
    expect(wrapper.emitted('reset-backend-token')).toEqual([[]])
  })
})

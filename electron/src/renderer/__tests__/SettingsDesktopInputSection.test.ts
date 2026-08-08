import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsDesktopInputSection from '../domains/settings/components/SettingsDesktopInputSection.vue'

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
})

const ElSwitchStub = defineComponent({
  emits: ['change'],
  template: '<button data-testid="toggle-talk" @click="$emit(\'change\', true)">toggle</button>',
})

const ElSelectStub = defineComponent({
  props: ['modelValue'],
  emits: ['change'],
  template: '<select data-testid="mouse-button" :value="modelValue" @change="$emit(\'change\', Number($event.target.value))"><slot /></select>',
})

const ElInputStub = defineComponent({
  props: ['modelValue'],
  emits: ['focus', 'blur', 'keydown'],
  template: '<input data-testid="shortcut" :value="modelValue" readonly @focus="$emit(\'focus\')" @blur="$emit(\'blur\')" @keydown="$emit(\'keydown\', $event)">',
})

const inputState = () => ({
  settings: {
    pushToTalk: { enabled: true, mouseButton: 4 as const },
    keyboard: { interact: 'Control+Space', lock: 'Control+L', openPanel: 'Control+O', toggleVision: 'Control+V' },
  },
  status: {
    mouseHookAvailable: true,
    pushToTalkActive: true,
    keyboard: { interact: true, lock: true, openPanel: true, toggleVision: false },
    errors: [],
  },
  available: true,
  loading: false,
  error: '',
})

const mountSection = () => mount(SettingsDesktopInputSection, {
  props: { state: inputState() },
  global: {
    stubs: {
      'el-alert': { template: '<div><slot /></div>' },
      'el-button': ElButtonStub,
      'el-card': { template: '<section><slot name="header" /><slot /></section>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-icon': { template: '<i><slot /></i>' },
      'el-input': ElInputStub,
      'el-option': { template: '<option><slot /></option>' },
      'el-select': ElSelectStub,
      'el-switch': ElSwitchStub,
      'el-tag': { template: '<span><slot /></span>' },
    },
  },
})

describe('SettingsDesktopInputSection', () => {
  it('emits parent-owned input actions', async () => {
    const wrapper = mountSection()

    await wrapper.get('[data-testid="reset-input-bindings"]').trigger('click')
    await wrapper.get('[data-testid="toggle-talk"]').trigger('click')
    await wrapper.get('[data-testid="mouse-button"]').setValue('5')
    await wrapper.get('[data-testid="shortcut"]').trigger('keydown', { key: 'Space', ctrlKey: true })

    expect(wrapper.emitted('reset')).toEqual([[]])
    expect(wrapper.emitted('set-push-to-talk-enabled')).toEqual([[true]])
    expect(wrapper.emitted('set-push-to-talk-mouse-button')).toEqual([[5]])
    expect(wrapper.emitted('capture-keyboard')?.[0]?.[0]).toBe('interact')
  })

  it('shows unavailable state without rendering editable controls as active', async () => {
    const wrapper = await mount(SettingsDesktopInputSection, {
      props: { state: { ...inputState(), available: false } },
      global: { stubs: { 'el-card': { template: '<section><slot name="header" /><slot /></section>' }, 'el-tag': true, 'el-button': ElButtonStub, 'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' }, 'el-form': { template: '<form><slot /></form>' }, 'el-switch': true, 'el-select': true, 'el-input': true, 'el-input-number': true, 'el-option': true, 'el-icon': true } },
    })

    expect(wrapper.text()).toContain('桌面输入')
    expect(wrapper.text()).toContain('Electron')
  })
})

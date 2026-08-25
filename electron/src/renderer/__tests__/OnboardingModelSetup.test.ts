import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OnboardingModelSetup from '../domains/onboarding/components/OnboardingModelSetup.vue'

const mocks = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), testLlm: vi.fn() }))

vi.mock('../api/client', () => ({ settingsClient: mocks }))
vi.mock('../api/clients/settings-client', async importOriginal => {
  const original = await importOriginal<typeof import('../api/clients/settings-client')>()
  return { ...original, settingsClient: mocks }
})

const global = {
  stubs: {
    'el-form': { template: '<form @submit.prevent><slot /></form>' },
    'el-form-item': { template: '<label><slot /></label>' },
    'el-select': {
      props: ['modelValue'],
      emits: ['update:modelValue', 'change'],
      template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
    },
    'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
    'el-input': {
      props: ['modelValue', 'type'],
      emits: ['update:modelValue'],
      template: '<input :type="type || \'text\'" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
    },
    'el-button': { template: '<button type="submit"><slot /></button>' },
    'el-icon': { template: '<i><slot /></i>' },
  },
}

describe('OnboardingModelSetup', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
    mocks.load.mockResolvedValue({ llm: { provider: 'custom', base_url: '', api_key: '', model: '' } })
    mocks.save.mockResolvedValue({ status: 'success' })
  })

  it('saves and genuinely tests the selected provider without exposing the credential in text', async () => {
    mocks.testLlm.mockResolvedValue({ ok: true, status: 'ok' })
    const wrapper = mount(OnboardingModelSetup, { global })
    await flushPromises()
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('model-chat')
    await inputs[1]!.setValue('http://localhost:11434/v1')
    await inputs[2]!.setValue('secret-value')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({
      llm: expect.objectContaining({ model: 'model-chat', api_key: 'secret-value' }),
    }))
    expect(mocks.testLlm).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('completed')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('secret-value')
  })

  it('preserves entered values after a failed test so retry does not require re-entry', async () => {
    mocks.testLlm.mockResolvedValue({ ok: false, message: 'Provider unavailable' })
    const wrapper = mount(OnboardingModelSetup, { global })
    await flushPromises()
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('kept-model')
    await inputs[1]!.setValue('http://localhost:1234/v1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Provider unavailable')
    expect((inputs[0]!.element as HTMLInputElement).value).toBe('kept-model')
    expect((inputs[1]!.element as HTMLInputElement).value).toBe('http://localhost:1234/v1')
  })
})

import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  productMetricsConsent: vi.fn(),
  patchProductMetricsConsent: vi.fn(),
}))

vi.mock('../api/clients/system-client', () => ({
  systemClient: mocks,
}))

import SettingsProductMetricsConsentSection from '../domains/settings/components/SettingsProductMetricsConsentSection.vue'

const mountSection = () => mount(SettingsProductMetricsConsentSection, {
  global: {
    stubs: {
      'el-card': { template: '<div><slot name="header" /><slot /></div>' },
      'el-tag': { template: '<span><slot /></span>' },
      'el-alert': { template: '<div><slot /></div>' },
      SettingsSectionHeader: { template: '<div><slot name="status" /></div>' },
      'el-switch': defineComponent({
        props: { modelValue: Boolean, disabled: Boolean, loading: Boolean },
        emits: ['change'],
        setup(props, { attrs, emit }) {
          return () => h('input', {
            ...attrs,
            type: 'checkbox',
            checked: props.modelValue,
            disabled: props.disabled,
            onChange: (event: Event) => emit('change', (event.target as HTMLInputElement).checked),
          })
        },
      }),
    },
  },
})

describe('SettingsProductMetricsConsentSection', () => {
  afterEach(() => vi.clearAllMocks())

  it('hydrates the switch from the authenticated backend snapshot', async () => {
    mocks.productMetricsConsent.mockResolvedValueOnce({ consented: true, scope: 'local_product_metrics', transport: 'not_configured' })
    const wrapper = mountSection()

    await vi.waitFor(() => expect(mocks.productMetricsConsent).toHaveBeenCalledOnce())
    await nextTick()

    expect(wrapper.get('[data-testid="product-metrics-consent"]').element.checked).toBe(true)
    expect(wrapper.text()).toContain('传输：未配置')
  })

  it('rolls back the switch when the consent patch fails', async () => {
    mocks.productMetricsConsent.mockResolvedValueOnce({ consented: false, scope: 'local_product_metrics', transport: 'not_configured' })
    mocks.patchProductMetricsConsent.mockRejectedValueOnce(new Error('conflict'))
    const wrapper = mountSection()
    await vi.waitFor(() => expect(mocks.productMetricsConsent).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(wrapper.get('[role="status"]').text()).toContain('授权状态已同步'))

    const input = wrapper.get('[data-testid="product-metrics-consent"]')
    await input.setValue(true)
    await vi.waitFor(() => expect(mocks.patchProductMetricsConsent).toHaveBeenCalledWith(true))
    await nextTick()

    expect(input.element.checked).toBe(false)
    expect(wrapper.find('[title="conflict"]').exists()).toBe(true)
  })
})

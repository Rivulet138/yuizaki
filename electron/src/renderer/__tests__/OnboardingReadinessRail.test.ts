import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { OnboardingProbeResult } from '../../shared/onboarding-readiness'
import OnboardingReadinessRail from '../domains/onboarding/components/OnboardingReadinessRail.vue'
import { setLocale } from '../i18n'

const createProbe = (overrides: Partial<OnboardingProbeResult> = {}): OnboardingProbeResult => ({
  id: 'llm.model_chat',
  label: 'Chat model',
  status: 'unavailable',
  requiredForText: true,
  dependencies: [],
  timeoutMs: 1_000,
  message: 'Provider secret diagnostic must stay hidden',
  evidence: { category: 'transport' },
  repairActionId: null,
  ...overrides,
})

const mountRail = (probe: OnboardingProbeResult) => mount(OnboardingReadinessRail, {
  props: { probes: [probe] },
  global: {
    stubs: {
      'el-icon': { template: '<i><slot /></i>' },
      'el-button': {
        emits: ['click'],
        template: '<button @click="$emit(\'click\')"><slot /></button>',
      },
    },
  },
})

describe('OnboardingReadinessRail diagnostics', () => {
  beforeEach(async () => {
    await setLocale('zh-CN', { persistSettings: false })
  })

  it('hides raw diagnostics behind localized generic copy in Chinese and Japanese', async () => {
    const raw = 'Provider secret diagnostic must stay hidden'
    const zh = mountRail(createProbe({ message: raw }))
    expect(zh.text()).toContain('无法获取最新检查结果')
    expect(zh.text()).not.toContain(raw)
    zh.unmount()

    await setLocale('ja-JP', { persistSettings: false })
    const ja = mountRail(createProbe({ message: raw }))
    expect(ja.text()).toContain('最新の確認結果を取得できませんでした')
    expect(ja.text()).not.toContain(raw)
  })

  it('uses only closed translated message keys', () => {
    const wrapper = mountRail(createProbe({
      messageKey: 'onboarding.interrupted',
      message: 'raw interrupted detail',
      evidence: {},
    }))

    expect(wrapper.text()).toContain('上次就绪检查意外中断')
    expect(wrapper.text()).not.toContain('raw interrupted detail')
  })

  it('shows bounded raw diagnostics in English', async () => {
    await setLocale('en-US', { persistSettings: false })
    const raw = `diagnostic-${'x'.repeat(600)}`
    const wrapper = mountRail(createProbe({ message: raw }))
    const displayed = wrapper.find('.readiness-copy p').text()

    expect(displayed).toBe(raw.slice(0, 500))
  })

  it('offers a direct model settings action for an unresolved model probe', async () => {
    const wrapper = mountRail(createProbe({ id: 'llm.model_chat', status: 'needs_user' }))
    const settingsButton = wrapper.findAll('button').find(button => button.text().includes('打开模型与语音设置'))

    expect(settingsButton).toBeDefined()
    await settingsButton!.trigger('click')
    expect(wrapper.emitted('repair')).toEqual([['navigate:settings']])
  })

  it('offers a direct pet settings action for an unavailable avatar', async () => {
    const wrapper = mountRail(createProbe({ id: 'host.avatar', label: 'Avatar', requiredForText: false }))
    const settingsButton = wrapper.findAll('button').find(button => button.text().includes('打开桌宠设置'))

    expect(settingsButton).toBeDefined()
    await settingsButton!.trigger('click')
    expect(wrapper.emitted('repair')).toEqual([['navigate:pet']])
  })
})

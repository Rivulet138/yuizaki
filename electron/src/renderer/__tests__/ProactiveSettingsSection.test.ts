import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { syncLocaleFromSettings } from '../i18n'

const mocks = vi.hoisted(() => ({
  confirm: vi.fn(),
  success: vi.fn(),
  load: vi.fn(async () => true),
  updateSettings: vi.fn(async () => true),
  deleteFrame: vi.fn(async () => true),
  submitFeedback: vi.fn(async () => true),
  invalidate: vi.fn(),
  pending: false,
  frames: [] as Array<Record<string, unknown>>,
  settings: {
    schemaVersion: 'yuizaki.proactive-settings.v1' as const,
    workspaceId: 'default',
    revision: 1,
  updatedAt: 1_787_097_600,
    enabled: true,
    sourceEnabled: { completed_turn_followup: true },
    dnd: false,
    quietHours: { enabled: true, start: '22:00', end: '07:00', timezone: 'Asia/Shanghai' },
    dailyBudget: 3,
    cooldownSeconds: 600,
    retentionDays: 7,
    policyVersion: 'policy-v1',
  },
}))

vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: { success: mocks.success },
  ElMessageBox: { confirm: mocks.confirm },
}))

vi.mock('../app/composables/useProactiveControls', async () => {
  const { computed, ref } = await import('vue')
  return {
    useProactiveControls: () => ({
      settings: ref(mocks.settings),
      visibleFrames: computed(() => mocks.frames),
      loaded: ref(true),
      policyClosed: ref(false),
      loading: ref(false),
      saving: ref(false),
      error: ref(null),
      load: mocks.load,
      updateSettings: mocks.updateSettings,
      deleteFrame: mocks.deleteFrame,
      submitFeedback: mocks.submitFeedback,
      isFeedbackPending: () => mocks.pending,
      invalidate: mocks.invalidate,
    }),
  }
})

import ProactiveSettingsSection from '../app/components/ProactiveSettingsSection.vue'

const opportunity = {
  jobId: 'job-1',
  requestId: 'request-1',
  sourceKind: 'completed_turn_followup' as const,
  sourceId: 'turn-1',
  triggerReason: 'SECRET_RAW_BACKEND_REASON',
  expiresAt: 1_800_000_000,
  frameId: 'frame-1',
}

const mountSection = () => mount(ProactiveSettingsSection, {
  props: { visible: true, workspaceId: 'default', opportunity },
  attachTo: document.body,
})

describe('ProactiveSettingsSection', () => {
  afterEach(() => {
    vi.clearAllMocks()
    mocks.pending = false
    mocks.frames = []
    syncLocaleFromSettings('zh-CN')
    document.body.innerHTML = ''
  })

  it.each([
    ['zh-CN', '主动陪伴', '符合已启用的本地触发条件'],
    ['en-US', 'Proactive companion', 'An enabled local trigger condition was met'],
    ['ja-JP', 'プロアクティブなコンパニオン', '有効なローカルトリガー条件に一致しました'],
  ] as const)('uses the closed localized reason catalog in %s', async (locale, title, reason) => {
    syncLocaleFromSettings(locale)
    const wrapper = mountSection()
    await nextTick()
    expect(wrapper.text()).toContain(title)
    expect(wrapper.text()).toContain(reason)
    expect(wrapper.text()).not.toContain('SECRET_RAW_BACKEND_REASON')
    expect(wrapper.text()).not.toContain('raw content')
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
  })

  it('disables all feedback while one acknowledgement is pending', async () => {
    mocks.pending = true
    const wrapper = mountSection()
    const buttons = wrapper.findAll('[data-testid^="proactive-feedback-"]')
    expect(buttons).toHaveLength(5)
    expect(buttons.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('confirms never-source, waits for acknowledgement, and restores keyboard focus', async () => {
    mocks.confirm.mockResolvedValueOnce('confirm')
    const wrapper = mountSection()
    const button = wrapper.get('[data-testid="proactive-feedback-never_source"]')
    button.element.focus()
    await button.trigger('click')
    await vi.waitFor(() => expect(mocks.submitFeedback).toHaveBeenCalledWith(opportunity, 'never_source'))
    expect(mocks.confirm).toHaveBeenCalledOnce()
    expect(document.activeElement).toBe(button.element)
    expect(mocks.success).toHaveBeenCalledOnce()
  })

  it('emits complete backend setting patches from keyboard-focusable native controls', async () => {
    const wrapper = mountSection()
    const dnd = wrapper.get('[data-testid="proactive-dnd"]')
    dnd.element.focus()
    await dnd.setValue(true)
    await wrapper.get('[data-testid="proactive-daily-budget"]').setValue('5')
    await wrapper.get('[data-testid="proactive-daily-budget"]').trigger('change')
    expect(document.activeElement).toBe(dnd.element)
    expect(mocks.updateSettings).toHaveBeenCalledWith({ dnd: true })
    expect(mocks.updateSettings).toHaveBeenCalledWith({ dailyBudget: 5 })
  })

  it('uses the shared backend numeric limits and clamps outgoing patches', async () => {
    const wrapper = mountSection()
    const daily = wrapper.get('[data-testid="proactive-daily-budget"]')
    const cooldown = wrapper.get('[data-testid="proactive-cooldown"]')
    const retention = wrapper.get('[data-testid="proactive-retention"]')
    expect([daily.attributes('min'), daily.attributes('max')]).toEqual(['1', '20'])
    expect([cooldown.attributes('min'), cooldown.attributes('max')]).toEqual(['0', '604800'])
    expect([retention.attributes('min'), retention.attributes('max')]).toEqual(['1', '90'])

    await daily.setValue('0')
    await daily.trigger('change')
    await cooldown.setValue('700000')
    await cooldown.trigger('change')
    await retention.setValue('100')
    await retention.trigger('change')
    expect(mocks.updateSettings).toHaveBeenCalledWith({ dailyBudget: 1 })
    expect(mocks.updateSettings).toHaveBeenCalledWith({ cooldownSeconds: 604800 })
    expect(mocks.updateSettings).toHaveBeenCalledWith({ retentionDays: 90 })
  })

  it('uses a named icon button for frame deletion without text glyph fallbacks', () => {
    mocks.frames = [{
      frameId: 'frame-1',
      sourceKind: 'completed_turn_followup',
      expiresAt: 1_787_184_000,
    }]
    const wrapper = mountSection()
    const button = wrapper.get('.icon-action')
    expect(button.attributes('aria-label')).toBeTruthy()
    expect(button.attributes('title')).toBe(button.attributes('aria-label'))
    expect(wrapper.html()).not.toContain('>×<')
    expect(wrapper.html()).not.toContain('>脳<')
  })
})

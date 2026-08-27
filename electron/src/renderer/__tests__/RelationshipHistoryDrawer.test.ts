import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const relationshipHistory = vi.hoisted(() => vi.fn())

vi.mock('../api/clients/companion-client', () => ({
  companionClient: {
    list: vi.fn(async () => ({ companions: [] })),
    relationshipHistory,
  },
}))

import RelationshipHistoryDrawer from '../domains/pet/components/RelationshipHistoryDrawer.vue'
import { useCompanionStore } from '../stores/companionStore'

const payload = {
  companion_id: 'default',
  events: [
    { kind: 'support', mood: '平静', affinity: 0.72, energy: 0.58, text: '完成一次支持互动', timestamp: '2026-08-27T10:30:00Z', scope: 'workspace', importance: 0.6, milestone: false },
    { kind: 'gratitude', mood: '开心', affinity: 0.81, energy: 0.66, text: '记录重要里程碑', timestamp: '2026-08-28T09:00:00Z', scope: 'global', importance: 0.95, milestone: true },
  ],
  grouped: {},
  milestones: [],
  summary: {
    event_count: 2,
    high_importance_count: 1,
    global_count: 1,
    workspace_count: 1,
    milestone_count: 1,
    recent_trust_shift_count: 0,
    recent_gratitude_count: 1,
    relationship_stage: '熟悉期',
    proactive_budget: 2,
    relationship_trend: '升温',
  },
}

describe('RelationshipHistoryDrawer', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setActivePinia(createPinia())
    const store = useCompanionStore()
    store.companions = [{ id: 'default', name: 'Yui', created_at: null, updated_at: null }]
    relationshipHistory.mockResolvedValue(payload)
  })

  it('loads the active companion summary and filters milestone events', async () => {
    const wrapper = mount(RelationshipHistoryDrawer, {
      props: { modelValue: true },
      global: {
        stubs: {
          'el-drawer': { props: ['modelValue', 'title'], template: '<aside><h2>{{ title }}</h2><slot /></aside>' },
          'el-segmented': { props: ['modelValue', 'options'], emits: ['update:modelValue'], template: '<button data-testid="milestone-mode" @click="$emit(\'update:modelValue\', \'milestones\')">里程碑</button>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': { template: '<span><slot /></span>' },
          'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
          'el-icon': { template: '<i><slot /></i>' },
        },
      },
    })
    await flushPromises()

    expect(relationshipHistory).toHaveBeenCalledWith('default', 100)
    expect(wrapper.text()).toContain('熟悉期')
    expect(wrapper.text()).toContain('升温')
    expect(wrapper.text()).toContain('完成一次支持互动')
    expect(wrapper.text()).toContain('记录重要里程碑')

    await wrapper.get('[data-testid="milestone-mode"]').trigger('click')
    expect(wrapper.text()).not.toContain('完成一次支持互动')
    expect(wrapper.text()).toContain('记录重要里程碑')
  })

  it('keeps the retry command when loading fails', async () => {
    relationshipHistory.mockRejectedValueOnce(new Error('history unavailable'))
    const wrapper = mount(RelationshipHistoryDrawer, {
      props: { modelValue: true },
      global: {
        stubs: {
          'el-drawer': { props: ['modelValue', 'title'], template: '<aside><slot /></aside>' },
          'el-segmented': true,
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': true,
          'el-empty': true,
          'el-icon': true,
        },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('history unavailable')
    await wrapper.get('.retry-btn').trigger('click')
    expect(relationshipHistory).toHaveBeenCalledTimes(2)
  })
})

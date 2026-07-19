import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SessionRail from '../domains/chat/components/SessionRail.vue'

vi.mock('@/api/client', () => ({
  systemClient: {
    exportData: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
  },
}))

const sessions = [
  {
    id: 'alpha-old',
    workspace_id: 'alpha',
    title: '旧任务',
    summary: null,
    pinned: false,
    created_at: '2026-01-01T00:00:00.000Z',
    updated_at: '2026-01-01T00:00:00.000Z',
    message_count: 1,
  },
  {
    id: 'alpha-pinned',
    workspace_id: 'alpha',
    title: '项目置顶',
    summary: null,
    pinned: true,
    created_at: '2026-01-02T00:00:00.000Z',
    updated_at: '2026-01-02T00:00:00.000Z',
    message_count: 2,
  },
  {
    id: 'beta-session',
    workspace_id: 'beta',
    title: 'Beta 会话',
    summary: null,
    pinned: true,
    created_at: '2026-01-03T00:00:00.000Z',
    updated_at: '2026-01-03T00:00:00.000Z',
    message_count: 3,
  },
  {
    id: 'default-session',
    workspace_id: 'default',
    title: '日常闲聊',
    summary: null,
    pinned: false,
    created_at: '2026-01-04T00:00:00.000Z',
    updated_at: '2026-01-04T00:00:00.000Z',
    message_count: 4,
  },
]

const mountRail = () => mount(SessionRail, {
  props: {
    sessions,
    activeSessionId: 'alpha-pinned',
    activeWorkspaceId: 'alpha',
    workspaceNames: {
      alpha: 'Alpha',
      beta: 'Beta',
    },
  },
  global: {
    stubs: {
      'el-button': { template: '<button><slot /></button>' },
      'el-dropdown': { template: '<div><slot /></div>' },
      'el-dropdown-menu': { template: '<div><slot /></div>' },
      'el-dropdown-item': { template: '<button><slot /></button>' },
      'el-icon': { template: '<i><slot /></i>' },
      Loading: true,
      MoreFilled: true,
      Plus: true,
      Search: true,
      Star: true,
      StarFilled: true,
    },
  },
})

describe('SessionRail grouping', () => {
  it('keeps pinned sessions inside their project group and splits other projects', () => {
    const wrapper = mountRail()
    const text = wrapper.text()

    expect(text).toContain('本项目 2 / 全部 4')
    expect(text).toContain('Alpha 项目')
    expect(text).toContain('Beta 项目')
    expect(text).toContain('普通对话')
    expect(text).not.toContain('其他项目')

    const alphaTitle = text.indexOf('Alpha 项目')
    const alphaPinned = text.indexOf('项目置顶')
    const alphaOld = text.indexOf('旧任务')
    const betaTitle = text.indexOf('Beta 项目')
    const betaSession = text.indexOf('Beta 会话')

    expect(alphaPinned).toBeGreaterThan(alphaTitle)
    expect(alphaPinned).toBeLessThan(alphaOld)
    expect(betaSession).toBeGreaterThan(betaTitle)
  })

  it('filters sessions by workspace display name', async () => {
    const wrapper = mountRail()
    await wrapper.find('.search-input').setValue('Beta')

    expect(wrapper.text()).toContain('Beta 项目')
    expect(wrapper.text()).toContain('Beta 会话')
    expect(wrapper.text()).not.toContain('Alpha 项目')
    expect(wrapper.text()).not.toContain('日常闲聊')
  })
})

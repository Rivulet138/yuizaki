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

const mountRail = (extraProps: Record<string, unknown> = {}) => mount(SessionRail, {
  props: {
    sessions,
    activeSessionId: 'alpha-pinned',
    activeWorkspaceId: 'alpha',
    workspaceNames: {
      alpha: 'Alpha',
      beta: 'Beta',
    },
    ...extraProps,
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

  it('renames a session inline without selecting it', async () => {
    const wrapper = mountRail()
    const session = wrapper.findAll('.session-item').find((item) => item.text().includes('旧任务'))
    expect(session).toBeDefined()

    await session!.find('.title').trigger('dblclick')
    const input = session!.find('.session-rename-input')
    await input.setValue('  新标题  ')
    await input.trigger('keydown.enter')

    expect(wrapper.emitted('rename-session')).toEqual([['alpha-old', '新标题']])
    expect(wrapper.emitted('select-session')).toBeUndefined()
  })

  it('shows draft, running, and unread state on the owning sessions only', () => {
    const wrapper = mountRail({
      draftSessionIds: ['alpha-old'],
      runningSessionIds: ['beta-session'],
      unreadSessionIds: ['default-session'],
    })

    const byTitle = (title: string) => wrapper.findAll('.session-item').find((item) => item.text().includes(title))
    expect(byTitle('旧任务')?.text()).toContain('草稿')
    expect(byTitle('旧任务')?.text()).not.toContain('生成中')
    expect(byTitle('Beta 会话')?.text()).toContain('生成中')
    expect(byTitle('日常闲聊')?.text()).toContain('新回复')
  })

  it('keeps archived sessions out of the daily list and allows restoring them', async () => {
    const archivedSession = {
      ...sessions[0],
      id: 'alpha-archived',
      title: '已归档任务',
      archived: true,
    }
    const wrapper = mountRail({ sessions: [...sessions, archivedSession] })

    expect(wrapper.text()).not.toContain('已归档任务')
    await wrapper.get('[data-testid="session-archive-filter"]').trigger('click')
    expect(wrapper.text()).toContain('已归档任务')

    ;(wrapper.vm as unknown as { handleMoreCommand: (command: string, session: typeof archivedSession) => void })
      .handleMoreCommand('archive', archivedSession)
    expect(wrapper.emitted('archive-session')).toEqual([['alpha-archived', false]])
  })
})

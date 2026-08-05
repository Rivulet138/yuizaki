import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { markRaw } from 'vue'

import AppSidebar from '../app/AppSidebar.vue'

const icon = markRaw({ template: '<span />' })

const mountSidebar = (adminMenus = [{ id: 'overview', title: '运行总览', icon }]) => mount(AppSidebar, {
  props: {
    activeWorkspaceId: 'default',
    menus: [{ id: 'companion', title: '桌宠首页', icon }],
    adminMenus,
  },
  global: {
    stubs: {
      RouterLink: {
        props: ['to'],
        template: '<a :href="to"><slot /></a>',
      },
      'el-icon': { template: '<i><slot /></i>' },
    },
  },
})

describe('AppSidebar', () => {
  it('keeps canonical links visible and compatibility links disclosed', async () => {
    const wrapper = mountSidebar([
      { id: 'tool', title: 'Capabilities', icon },
      { id: 'plugins', title: 'Plugins', icon },
      { id: 'agent-governance', title: 'Governance', icon },
      { id: 'agent-trace', title: 'Tasks', icon },
      { id: 'agent-trace-admin', title: 'Trace archive', icon },
    ])
    await wrapper.get('.admin-toggle').trigger('click')

    expect(wrapper.get('a[href="/w/default/tool"]').text()).toContain('Capabilities')
    expect(wrapper.get('a[href="/w/default/agent-trace"]').text()).toContain('Tasks')

    const relatedRoutes = wrapper.findAll('details.related-routes')
    expect(relatedRoutes).toHaveLength(2)
    expect(relatedRoutes[0].attributes('open')).toBeUndefined()
    expect(relatedRoutes[0].get('a[href="/w/default/plugins"]').text()).toContain('Plugins')
    expect(relatedRoutes[0].get('a[href="/w/default/agent-governance"]').text()).toContain('Governance')
    expect(relatedRoutes[1].get('a[href="/w/default/agent-trace-admin"]').text()).toContain('Trace archive')
  })

  it('keeps advanced tools collapsed until the user opens them', async () => {
    const wrapper = mountSidebar()

    expect(wrapper.text()).not.toContain('运行总览')
    const toggle = wrapper.get('button[aria-expanded="false"]')
    expect(toggle.attributes('aria-label')).toBe('高级工具')
    expect(toggle.attributes('title')).toBe('高级工具')
    await toggle.trigger('click')

    expect(wrapper.text()).toContain('运行总览')
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true')
  })

  it('opens desktop pet scene settings from the persistent sidebar', async () => {
    const wrapper = mountSidebar()
    const settingsButton = wrapper.get('button[title="桌宠场景设置"]')

    await settingsButton.trigger('click')

    expect(wrapper.emitted('open-workspace-settings')).toEqual([[]])
  })

  it('groups skills, connections, and governance under one localized admin section', async () => {
    const wrapper = mountSidebar([
      { id: 'overview', title: '运行总览', icon },
      { id: 'tool', title: '本地能力', icon },
      { id: 'plugins', title: '桌宠技能', icon },
      { id: 'agent-governance', title: 'Agent 治理', icon },
      { id: 'agent-trace-admin', title: '运行追踪', icon },
    ])
    await wrapper.get('.admin-toggle').trigger('click')

    const permissions = wrapper.get('section[aria-label="技能、连接与权限"]')
    expect(permissions.text()).toContain('本地能力')
    expect(permissions.text()).toContain('桌宠技能')
    expect(permissions.text()).toContain('Agent 治理')
    expect(permissions.text()).not.toContain('运行追踪')
  })
})

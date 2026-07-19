import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { markRaw } from 'vue'

import AppSidebar from '../app/AppSidebar.vue'

const icon = markRaw({ template: '<span />' })

const mountSidebar = () => mount(AppSidebar, {
  props: {
    activeWorkspaceId: 'default',
    menus: [{ id: 'companion', title: '桌宠首页', icon }],
    adminMenus: [{ id: 'overview', title: '运行总览', icon }],
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
})

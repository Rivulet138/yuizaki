import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import WorkspaceDrawer from '../app/WorkspaceDrawer.vue'
import { syncLocaleFromSettings } from '../i18n'
import type { WorkspaceRecord } from '../../shared/workspace'


const RouterLinkStub = defineComponent({
  props: { to: { type: String, required: true } },
  setup(props, { attrs, slots }) {
    return () => h('a', { ...attrs, href: props.to }, slots.default?.())
  },
})

const global = {
  stubs: {
    'router-link': RouterLinkStub,
    'el-divider': { template: '<hr />' },
    'el-drawer': { props: ['title'], template: '<aside><h2>{{ title }}</h2><slot /></aside>' },
    'el-form': { template: '<form><slot /></form>' },
    'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
    'el-input': { props: ['modelValue'], emits: ['change'], template: '<input :value="modelValue" @change="$emit(\'change\', $event.target.value)" />' },
    'el-option': { template: '<option><slot /></option>' },
    'el-select': { props: ['modelValue'], emits: ['change'], template: '<select :value="modelValue" @change="$emit(\'change\', $event.target.value)"><slot /></select>' },
  },
}

const mountDrawer = (overrides: Record<string, unknown> = {}) => mount(WorkspaceDrawer, {
  props: {
    visible: true,
    workspace,
    companions: [{ id: 'companion-2', name: 'Companion 2' }] as never[],
    activeCompanion: null,
    muted: false,
    ...overrides,
  },
  global,
  attachTo: document.body,
})

const workspace = {
  id: 'default',
  name: 'Daily',
  description: '',
  companion_profile_id: 'default',
  default_model: 'custom-model',
  tool_preset: '["removed-tool"]',
  memory_scope: 'workspace',
  mcp_preset_id: 'removed-server',
  createdAt: '2026-07-18T00:00:00.000Z',
  updatedAt: '2026-07-18T00:00:00.000Z',
  context: {},
} as unknown as WorkspaceRecord

describe('WorkspaceDrawer', () => {
  afterEach(() => {
    syncLocaleFromSettings('zh-CN')
    document.body.innerHTML = ''
  })

  it('shows configured values with canonical links and no duplicate advanced selectors', () => {
    const wrapper = mountDrawer()

    expect(wrapper.text()).toContain('custom-model')
    expect(wrapper.text()).toContain('removed-tool')
    expect(wrapper.text()).toContain('removed-server')
    expect(wrapper.find('[data-testid="workspace-model-select"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="workspace-model-summary"]').attributes('href')).toBe('/w/default/settings')
    expect(wrapper.get('[data-testid="workspace-memory-summary"]').attributes('href')).toBe('/w/default/memory')
    expect(wrapper.get('[data-testid="workspace-tool-summary"]').attributes('href')).toBe('/w/default/tool')
    expect(wrapper.get('[data-testid="workspace-mcp-summary"]').attributes('href')).toBe('/w/default/agent-governance')
    expect(wrapper.get('[data-testid="workspace-companion-manage"]').attributes('href')).toBe('/w/default/pet')
  })

  it('emits only quick scene and companion field changes', async () => {
    const wrapper = mountDrawer()

    const inputs = wrapper.findAll('input')
    await inputs[0]?.setValue('Focus')
    await inputs[0]?.trigger('change')
    await wrapper.get('select').setValue('companion-2')

    expect(wrapper.emitted('update-field')).toContainEqual(['name', 'Focus'])
    expect(wrapper.emitted('update-field')).toContainEqual(['companion_profile_id', 'companion-2'])
    expect(wrapper.emitted('update-field')?.some(([field]) => ['default_model', 'memory_scope', 'tool_preset', 'mcp_preset_id'].includes(String(field)))).toBe(false)
  })

  it('does not expose companion CRUD or workspace management metadata', () => {
    const wrapper = mountDrawer()

    expect(wrapper.text()).not.toMatch(/新建|编辑|删除/)
    expect(wrapper.text()).not.toContain(workspace.id)
    expect(wrapper.text()).not.toContain(workspace.updatedAt)
    expect(wrapper.emitted('create-companion')).toBeUndefined()
    expect(wrapper.find('[data-testid="workspace-metadata"]').exists()).toBe(false)
  })

  it('keeps mute as a runtime shortcut and moves proactive authority into the backend section', async () => {
    const wrapper = mountDrawer()

    await wrapper.get('[data-testid="workspace-mute"]').setValue(true)
    expect(wrapper.emitted('set-muted')).toEqual([[true]])
    expect(wrapper.find('[data-testid="workspace-dnd"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="workspace-proactivity-standard"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="proactive-dnd"]').exists()).toBe(true)
  })

  it('reacts to locale changes and keeps canonical controls keyboard focusable', async () => {
    const wrapper = mountDrawer()

    syncLocaleFromSettings('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('Workspace settings')
    expect(wrapper.text()).toContain('Do not disturb')

    syncLocaleFromSettings('ja-JP')
    await nextTick()
    expect(wrapper.text()).toContain('ワークスペース設定')
    expect(wrapper.text()).toContain('おやすみモード')

    const manageLink = wrapper.get('[data-testid="workspace-companion-manage"]')
    manageLink.element.focus()
    expect(document.activeElement).toBe(manageLink.element)
    const muteControl = wrapper.get('[data-testid="workspace-mute"]')
    muteControl.element.focus()
    expect(document.activeElement).toBe(muteControl.element)
  })
})

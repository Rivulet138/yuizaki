import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceDrawer from '../app/WorkspaceDrawer.vue'
import type { WorkspaceRecord } from '../../shared/workspace'

const systemClientMocks = vi.hoisted(() => ({
  capabilities: vi.fn(),
  mcp: vi.fn(),
}))
const settingsClientMocks = vi.hoisted(() => ({
  load: vi.fn(),
  listLlmModels: vi.fn(),
}))

vi.mock('../api/clients/system-client', () => ({
  systemClient: systemClientMocks,
}))
vi.mock('../api/clients/settings-client', () => ({
  settingsClient: settingsClientMocks,
}))

const ElementSelectStub = defineComponent({
  inheritAttrs: false,
  props: {
    modelValue: {
      type: [String, Array],
      default: '',
    },
    multiple: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['change'],
  setup(props, { attrs, emit, slots }) {
    return () => h('select', {
      ...attrs,
      multiple: props.multiple,
      value: props.modelValue,
      onChange: (event: Event) => {
        const select = event.target as HTMLSelectElement
        emit('change', props.multiple
          ? Array.from(select.selectedOptions).map((option) => option.value)
          : select.value)
      },
    }, slots.default?.())
  },
})

const ElementOptionStub = defineComponent({
  props: {
    label: {
      type: String,
      default: '',
    },
    value: {
      type: String,
      default: '',
    },
  },
  setup(props) {
    return () => h('option', { value: props.value }, props.label)
  },
})

const global = {
  stubs: {
    'el-alert': { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
    'el-button': { template: '<button><slot /></button>' },
    'el-divider': { template: '<hr />' },
    'el-drawer': { template: '<aside><slot /></aside>' },
    'el-form': { template: '<form><slot /></form>' },
    'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
    'el-input': { props: ['modelValue'], template: '<input :value="modelValue" />' },
    'el-option': ElementOptionStub,
    'el-select': ElementSelectStub,
  },
}

const workspace = {
  id: 'default',
  name: '日常陪伴',
  description: '',
  companion_profile_id: 'default',
  default_model: null,
  tool_preset: '["clock"]',
  memory_scope: 'workspace',
  mcp_preset_id: 'browser',
  createdAt: '2026-07-18T00:00:00.000Z',
  updatedAt: '2026-07-18T00:00:00.000Z',
  context: {},
} as unknown as WorkspaceRecord

describe('WorkspaceDrawer', () => {
  beforeEach(() => {
    systemClientMocks.capabilities.mockReset()
    systemClientMocks.mcp.mockReset()
    settingsClientMocks.load.mockReset()
    settingsClientMocks.listLlmModels.mockReset()
    settingsClientMocks.load.mockResolvedValue({
      llm: {
        provider: 'deepseek',
        base_url: 'https://api.deepseek.com/v1',
        api_key: '********',
        model: 'deepseek-chat',
        temperature: 0.7,
        top_p: 0.9,
        timeout: 30,
      },
    })
    settingsClientMocks.listLlmModels.mockResolvedValue({
      ok: true,
      models: ['deepseek-chat', 'deepseek-reasoner'],
    })
  })

  it('loads backend capabilities and saves functional tool and MCP selections', async () => {
    systemClientMocks.capabilities.mockResolvedValue({
      capabilities: [
        { id: 'clock', name: '时钟', description: '', type: 'tool', kind: 'builtin-tool', source: 'builtin', riskLevel: 'safe', requiresApproval: false },
        { id: 'browser.open', name: '打开浏览器', description: '', type: 'tool', kind: 'mcp-tool', source: 'browser', riskLevel: 'low', requiresApproval: false },
        { id: 'daily-summary', name: '日结', description: '', type: 'skill', kind: 'skill', source: 'builtin', riskLevel: 'safe', requiresApproval: false },
      ],
    })
    systemClientMocks.mcp.mockResolvedValue({
      servers: {
        browser: { name: 'browser', base_url: '', transport: 'stdio', enabled: true },
        calendar: { name: 'calendar', base_url: '', transport: 'stdio', enabled: true },
        offline: { name: 'offline', base_url: '', transport: 'stdio', enabled: false },
      },
      status: {},
    })

    const wrapper = mount(WorkspaceDrawer, {
      props: {
        visible: true,
        workspace,
        companions: [],
        activeCompanion: null,
      },
      global,
    })
    await flushPromises()

    expect(systemClientMocks.capabilities).toHaveBeenCalledTimes(1)
    expect(systemClientMocks.mcp).toHaveBeenCalledTimes(1)
    expect(settingsClientMocks.load).toHaveBeenCalledTimes(1)
    expect(settingsClientMocks.listLlmModels).toHaveBeenCalledWith({
      provider: 'deepseek',
      base_url: 'https://api.deepseek.com/v1',
      api_key: '********',
      timeout: 30,
    })
    expect(wrapper.text()).toContain('deepseek-chat')
    expect(wrapper.text()).toContain('deepseek-reasoner')
    expect(wrapper.text()).toContain('时钟')
    expect(wrapper.text()).toContain('打开浏览器')
    expect(wrapper.text()).not.toContain('日结')
    expect(wrapper.text()).toContain('browser')
    expect(wrapper.text()).toContain('offline（已停用）')
    expect(wrapper.text()).not.toContain('工具白名单')
    expect(wrapper.text()).not.toContain('MCP 服务预设')

    const toolSelect = wrapper.get('[data-testid="workspace-tool-select"]')
    await toolSelect.setValue(['clock', 'browser.open'])
    const mcpSelect = wrapper.get('[data-testid="workspace-mcp-select"]')
    await mcpSelect.setValue('calendar')
    const modelSelect = wrapper.get('[data-testid="workspace-model-select"]')
    await modelSelect.setValue('deepseek-reasoner')

    expect(wrapper.emitted('update-field')).toContainEqual([
      'tool_preset',
      '["browser.open","clock"]',
    ])
    expect(wrapper.emitted('update-field')).toContainEqual(['mcp_preset_id', 'calendar'])
    expect(wrapper.emitted('update-field')).toContainEqual(['default_model', 'deepseek-reasoner'])
  })

  it('keeps unknown saved capability ids selectable when the runtime catalog changes', async () => {
    systemClientMocks.capabilities.mockResolvedValue({ capabilities: [] })
    systemClientMocks.mcp.mockResolvedValue({ servers: {}, status: {} })

    const wrapper = mount(WorkspaceDrawer, {
      props: {
        visible: true,
        workspace: {
          ...workspace,
          default_model: 'custom-companion-model',
          tool_preset: '["removed-tool"]',
          mcp_preset_id: 'removed-server',
        },
        companions: [],
        activeCompanion: null,
      },
      global,
    })
    await flushPromises()

    expect(wrapper.text()).toContain('removed-tool（不可用）')
    expect(wrapper.text()).toContain('removed-server（不可用）')
    expect(wrapper.text()).toContain('custom-companion-model（当前）')
  })

  it('keeps manual model entry available when provider discovery fails', async () => {
    systemClientMocks.capabilities.mockResolvedValue({ capabilities: [] })
    systemClientMocks.mcp.mockResolvedValue({ servers: {}, status: {} })
    settingsClientMocks.listLlmModels.mockResolvedValue({
      ok: false,
      models: [],
      message: 'Provider unavailable',
    })

    const wrapper = mount(WorkspaceDrawer, {
      props: {
        visible: true,
        workspace,
        companions: [],
        activeCompanion: null,
      },
      global,
    })
    await flushPromises()

    expect(wrapper.text()).toContain('模型目录加载失败')
    expect(wrapper.get('[data-testid="workspace-model-select"]').attributes()).toHaveProperty('data-testid')
  })
})

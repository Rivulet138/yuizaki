import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GlobalDialogs from '../app/components/dialogs/GlobalDialogs.vue'
import { syncLocaleFromSettings } from '../i18n'
import { readFileSync } from 'node:fs'

const mocks = vi.hoisted(() => ({
  dialogStore: {
    permissionDialogVisible: true,
    permissionRequest: null as Record<string, unknown> | null,
    workspaceDrawerVisible: false,
    editCompanionDialogVisible: false,
    editCompanionTargetId: '',
    openEditCompanion: vi.fn(),
  },
  sendPermissionResponse: vi.fn(),
  publishRuntime: vi.fn(() => Promise.resolve(true)),
  setTtsEnabled: vi.fn(),
  setDoNotDisturb: vi.fn(() => Promise.resolve()),
  setProactivityPreset: vi.fn(() => true),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { prompt: vi.fn(), confirm: vi.fn() },
}))

vi.mock('@/stores/dialogStore', () => ({ useDialogStore: () => mocks.dialogStore }))
vi.mock('@/stores/workspaceStore', () => ({
  useWorkspaceStore: () => ({
    activeWorkspaceId: 'default',
    activeWorkspace: { context: {} },
    updateWorkspaceRemote: vi.fn(),
  }),
}))
vi.mock('@/stores/companionStore', () => ({
  useCompanionStore: () => ({
    companions: [],
    activeCompanion: null,
    createCompanion: vi.fn(),
    updateCompanion: vi.fn(),
    deleteCompanion: vi.fn(),
  }),
}))
vi.mock('@/stores/chatStore', () => ({
  useChatStore: () => ({
    chatOptions: { tts_enabled: true },
    setTtsEnabled: mocks.setTtsEnabled,
  }),
}))
vi.mock('@/net/socketClient', () => ({
  getSocketClient: () => ({ sendPermissionResponse: mocks.sendPermissionResponse }),
}))
vi.mock('@/app/runtime/companionRuntime', () => ({
  publishCompanionRuntimeEvent: mocks.publishRuntime,
}))
vi.mock('@/app/composables/useCompanionRuntimeBridge', () => ({
  useCompanionRuntimeBridge: () => ({
    applyActiveCompanionRuntime: vi.fn(),
    doNotDisturb: false,
    proactivityPreset: 'conservative',
    setDoNotDisturb: mocks.setDoNotDisturb,
    setProactivityPreset: mocks.setProactivityPreset,
  }),
}))

const ElDialogStub = {
  props: ['modelValue', 'beforeClose', 'title'],
  emits: ['update:modelValue', 'closed'],
  template: `
    <section>
      <h2>{{ title }}</h2>
      <button class="dismiss-x" @click="beforeClose(() => $emit('update:modelValue', false))">x</button>
      <button class="dismiss-escape" @click="beforeClose(() => $emit('update:modelValue', false))">escape</button>
      <button class="dismiss-backdrop" @click="beforeClose(() => $emit('update:modelValue', false))">backdrop</button>
      <slot />
      <slot name="footer" />
    </section>
  `,
}

const WorkspaceDrawerStub = {
  emits: ['set-muted', 'set-dnd', 'set-proactivity'],
  template: `
    <section>
      <button class="drawer-mute" @click="$emit('set-muted', true)">mute</button>
      <button class="drawer-dnd" @click="$emit('set-dnd', true)">dnd</button>
      <button class="drawer-proactivity" @click="$emit('set-proactivity', 'standard')">standard</button>
    </section>
  `,
}

const mountDialogs = () => mount(GlobalDialogs, {
  global: {
    stubs: {
      'el-dialog': ElDialogStub,
      'el-button': { template: '<button><slot /></button>' },
      'el-checkbox': { template: '<label><input type="checkbox" /><slot /></label>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
      'el-input': { template: '<input />' },
      'el-select': { template: '<select><slot /></select>' },
      'el-option': { props: ['label'], template: '<option>{{ label }}</option>' },
      WorkspaceDrawer: WorkspaceDrawerStub,
    },
  },
})

const request = () => ({
  request_id: 'permission-1',
  tool_name: 'write_file',
  risk_level: 'high',
  reason: 'needs approval',
  args: { path: 'notes.txt' },
})

describe('GlobalDialogs permission dismissal', () => {
  beforeEach(() => {
    mocks.dialogStore.permissionDialogVisible = true
    mocks.dialogStore.permissionRequest = request()
    mocks.sendPermissionResponse.mockReset()
    mocks.publishRuntime.mockClear()
    mocks.setTtsEnabled.mockClear()
    mocks.setDoNotDisturb.mockClear()
    mocks.setProactivityPreset.mockClear()
  })

  afterEach(() => syncLocaleFromSettings('zh-CN'))

  it('renders permission and profile controls in all supported locales', async () => {
    const wrapper = mountDialogs()

    syncLocaleFromSettings('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('Tool permission')
    expect(wrapper.text()).toContain('Remember this decision')
    expect(wrapper.text()).toContain('Edit companion profile')

    syncLocaleFromSettings('ja-JP')
    await nextTick()
    expect(wrapper.text()).toContain('ツール権限の確認')
    expect(wrapper.text()).toContain('この選択を記憶')
    expect(wrapper.text()).toContain('ペットプロフィールを編集')
  })

  it('contains no visible Chinese literals outside i18n resources', () => {
    const source = readFileSync('src/renderer/app/components/dialogs/GlobalDialogs.vue', 'utf8')
    expect(source).not.toMatch(/[一-龥]/u)
  })

  it('routes workspace shortcuts through the existing chat and companion runtime owners', async () => {
    const wrapper = mountDialogs()

    await wrapper.get('.drawer-mute').trigger('click')
    await wrapper.get('.drawer-dnd').trigger('click')
    await wrapper.get('.drawer-proactivity').trigger('click')
    await flushPromises()

    expect(mocks.setTtsEnabled).toHaveBeenCalledWith(false)
    expect(mocks.setDoNotDisturb).toHaveBeenCalledWith(true)
    expect(mocks.setProactivityPreset).toHaveBeenCalledWith('standard')
  })

  it.each(['dismiss-x', 'dismiss-escape', 'dismiss-backdrop'])('treats %s as an explicit denial', async (dismissClass) => {
    const wrapper = mountDialogs()

    await wrapper.get(`.${dismissClass}`).trigger('click')
    await flushPromises()

    expect(mocks.sendPermissionResponse).toHaveBeenCalledOnce()
    expect(mocks.sendPermissionResponse).toHaveBeenCalledWith('permission-1', false, false)
    expect(mocks.publishRuntime).toHaveBeenCalledWith({
      source: 'permission',
      permission: 'none',
      requestId: 'permission-1',
    })
  })

  it('allows an explicit permission decision exactly once', async () => {
    const wrapper = mountDialogs()

    await wrapper.get('[data-testid="permission-allow"]').trigger('click')
    await flushPromises()

    expect(mocks.sendPermissionResponse).toHaveBeenCalledOnce()
    expect(mocks.sendPermissionResponse).toHaveBeenCalledWith('permission-1', true, false)
    expect(mocks.publishRuntime).toHaveBeenCalledOnce()
  })

  it('uses the same idempotent denial path for the normal deny button', async () => {
    const wrapper = mountDialogs()
    const deny = wrapper.get('[data-testid="permission-deny"]')

    await deny.trigger('click')
    await wrapper.getComponent(ElDialogStub).vm.$emit('closed')
    await flushPromises()

    expect(mocks.sendPermissionResponse).toHaveBeenCalledOnce()
    expect(mocks.publishRuntime).toHaveBeenCalledOnce()
    expect(mocks.dialogStore.permissionRequest).toBeNull()
    expect(mocks.dialogStore.permissionDialogVisible).toBe(false)
  })
})

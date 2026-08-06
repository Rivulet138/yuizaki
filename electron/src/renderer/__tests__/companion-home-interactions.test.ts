import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import CompanionActivitySummary from '../domains/companion/components/CompanionActivitySummary.vue'
import CompanionHero from '../domains/companion/components/CompanionHero.vue'
import CompanionQuickActions from '../domains/companion/components/CompanionQuickActions.vue'
import CompanionPanel from '../domains/companion/views/CompanionPanel.vue'
import { useCompanionRuntimeBridge } from '../app/composables/useCompanionRuntimeBridge'
import { publishCompanionRuntimeEvent } from '../app/runtime/companionRuntime'
import { useChatStore } from '../stores/chatStore'

const apiMocks = vi.hoisted(() => ({
  companionRuntime: vi.fn(),
  getState: vi.fn(),
  setDoNotDisturb: vi.fn(),
  setModelSelection: vi.fn(),
  updateCompanionIdleProfile: vi.fn(),
  setBehaviorState: vi.fn(),
  triggerEmotion: vi.fn(),
  triggerMotion: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  chatClient: { getSocketClient: vi.fn() },
  systemClient: { companionRuntime: apiMocks.companionRuntime },
  settingsClient: { save: vi.fn() },
  petControlClient: {
    getState: apiMocks.getState,
    setDoNotDisturb: apiMocks.setDoNotDisturb,
    setModelSelection: apiMocks.setModelSelection,
    updateCompanionIdleProfile: apiMocks.updateCompanionIdleProfile,
    setBehaviorState: apiMocks.setBehaviorState,
    triggerEmotion: apiMocks.triggerEmotion,
    triggerMotion: apiMocks.triggerMotion,
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: messageMocks,
}))

vi.mock('@/stores/companionStore', () => ({
  useCompanionStore: () => ({
    loading: false,
    activeCompanion: {
      id: 'comp-1',
      name: 'Yui',
      avatar: null,
      model_type: 'live2d',
      model_id: 'yuizaki-live2d',
      support_style: 'gentle',
      energy_state: 0.8,
    },
    loadCompanions: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/stores/workspaceStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../stores/workspaceStore')>()
  return {
    ...actual,
    useWorkspaceStore: () => ({
      activeWorkspaceId: 'ws-1',
      activeWorkspace: { id: 'ws-1', context: {} },
    }),
  }
})

const petState = (doNotDisturb = false) => ({
  modelType: 'live2d',
  modelId: 'yuizaki-live2d',
  visible: true,
  doNotDisturb,
})

const runtimeSnapshot = {
  heartbeat: { running: true, tick_count: 1, persona: {}, events: [], behavior_events: [] },
  companion_state: { mood: 'warm', stage: 'stable' },
  memory_state: {
    profile_count: 1,
    semantic_count: 0,
    episodic_count: 0,
    relationship_count: 0,
    working_count: 0,
    reflective_count: 0,
    recent_signals: [],
    signal_summary: {},
  },
  relationship: { events: [], grouped: {}, milestones: [], summary: { relationship_stage: 'stable' } },
}

const global = {
  stubs: {
    PanelShell: { template: '<main><slot /></main>' },
    'router-link': {
      props: ['to'],
      template: '<a href="#" :data-to="to"><slot /></a>',
    },
    'el-alert': { props: ['title', 'description'], template: '<div>{{ title }} {{ description }}</div>' },
    'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
    'el-button': { template: '<button><slot /></button>' },
    'el-icon': { template: '<i><slot /></i>' },
    'el-switch': { template: '<input type="checkbox" />' },
    'el-select': { template: '<select><slot /></select>' },
    'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  },
}

const mountedWrappers: Array<{ unmount: () => void }> = []

const mountHome = async () => {
  const host = document.createElement('div')
  document.body.append(host)
  const wrapper = mount(CompanionPanel, { global, attachTo: host })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

describe('Companion Home interactions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
    vi.clearAllMocks()
    apiMocks.companionRuntime.mockResolvedValue(runtimeSnapshot)
    apiMocks.getState.mockResolvedValue(petState())
    apiMocks.setDoNotDisturb.mockImplementation(async (enabled: boolean) => petState(enabled))
    apiMocks.setModelSelection.mockResolvedValue(undefined)
    apiMocks.updateCompanionIdleProfile.mockResolvedValue(undefined)
    apiMocks.setBehaviorState.mockResolvedValue(undefined)
    apiMocks.triggerEmotion.mockResolvedValue(undefined)
    apiMocks.triggerMotion.mockResolvedValue(undefined)
  })

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
    document.body.replaceChildren()
    vi.restoreAllMocks()
  })

  it('exposes all canonical advanced routes', async () => {
    const bridge = useCompanionRuntimeBridge()
    expect(bridge.setProactivityPreset('standard')).toBe(true)
    expect(bridge.proactivityPreset.value).toBe('standard')

    const wrapper = await mountHome()
    const targets = wrapper.findAll('a').map((link) => link.attributes('data-to'))
    expect(targets).toEqual(expect.arrayContaining([
      '/w/ws-1/chat',
      '/w/ws-1/prompt',
      '/w/ws-1/persona-memory',
      '/w/ws-1/settings',
      '/w/ws-1/memory',
      '/w/ws-1/pet',
      '/w/ws-1/agent-governance',
      '/w/ws-1/agent-trace',
    ]))

    const talkLink = wrapper.get('[data-testid="companion-talk-action"]')
    talkLink.element.focus()
    expect(document.activeElement).toBe(talkLink.element)
  })

  it('composes an accessible first viewport with responsive daily commands', async () => {
    const wrapper = await mountHome()

    expect(wrapper.findComponent(CompanionHero).exists()).toBe(true)
    expect(wrapper.findComponent(CompanionQuickActions).exists()).toBe(true)
    expect(wrapper.findComponent(CompanionActivitySummary).exists()).toBe(true)
    expect(wrapper.get('[role="status"]').attributes('aria-live')).toBe('polite')

    const quickActions = readFileSync('src/renderer/domains/companion/components/CompanionQuickActions.vue', 'utf8')
    const hero = readFileSync('src/renderer/domains/companion/components/CompanionHero.vue', 'utf8')
    expect(quickActions).toContain('.command:focus-visible')
    expect(quickActions).toContain('@media (max-width: 760px)')
    expect(quickActions).toContain('grid-template-columns: repeat(2, minmax(0, 1fr))')
    expect(hero).toContain('overflow-wrap: anywhere')
    expect(hero).toContain('@media (max-width: 760px)')
  })

  it('keeps maintenance ownership and persisted presets outside Home', () => {
    const source = readFileSync('src/renderer/domains/companion/views/CompanionPanel.vue', 'utf8')

    expect(source).not.toMatch(/saveCompanion|handleDelete|heartbeatLatestBehavior/)
    expect(source).not.toMatch(/localStorage|setInterval/)
    expect(source).toContain('if (companionHomeLoading) return')
  })

  it('keeps authorization errors mutually exclusive from the successful empty state', () => {
    const source = readFileSync('src/renderer/domains/companion/views/CompanionPanel.vue', 'utf8')

    expect(source).toMatch(/<template v-if="companionLoadError">[\s\S]*<template v-else>/)
    expect(source).toContain("t('companion.home.authorizationRequired')")
  })

  it('dispatches mute and interrupt through the existing chat store', async () => {
    const chatStore = useChatStore()
    chatStore.state.isGenerating = true
    const mute = vi.spyOn(chatStore, 'setTtsEnabled').mockImplementation(() => undefined)
    const interrupt = vi.spyOn(chatStore, 'interrupt').mockImplementation(() => undefined)
    const wrapper = await mountHome()

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text().includes('静音'))?.trigger('click')
    await buttons.find((button) => button.text().includes('停止当前动作'))?.trigger('click')

    expect(mute).toHaveBeenCalledWith(false)
    expect(interrupt).toHaveBeenCalledOnce()
  })

  it('updates DND without proactive effects and keeps the last state when the client fails', async () => {
    const wrapper = await mountHome()
    const actions = wrapper.findComponent(CompanionQuickActions)

    actions.vm.$emit('set-dnd', true)
    await flushPromises()
    expect(apiMocks.setDoNotDisturb).toHaveBeenCalledWith(true)
    expect(actions.props('dnd')).toBe(true)
    expect(apiMocks.triggerEmotion).not.toHaveBeenCalled()
    expect(apiMocks.triggerMotion).not.toHaveBeenCalled()

    apiMocks.setDoNotDisturb.mockRejectedValueOnce(new Error('dnd unavailable'))
    actions.vm.$emit('set-dnd', false)
    await flushPromises()
    expect(actions.props('dnd')).toBe(true)
    expect(messageMocks.error).toHaveBeenCalledWith('dnd unavailable')
  })

  it('persists proactivity and rolls back the shared preset when storage fails', async () => {
    const wrapper = await mountHome()
    const actions = wrapper.findComponent(CompanionQuickActions)

    actions.vm.$emit('set-proactivity', 'standard')
    await flushPromises()
    expect(actions.props('proactivityPreset')).toBe('standard')
    expect(window.localStorage.getItem('yuizaki.companion.proactivity-preset')).toBe('standard')

    const storageFailure = vi.spyOn(window.localStorage, 'setItem').mockImplementationOnce(() => {
      throw new Error('storage unavailable')
    })
    actions.vm.$emit('set-proactivity', 'conservative')
    await flushPromises()
    expect(actions.props('proactivityPreset')).toBe('standard')
    expect(messageMocks.error).toHaveBeenCalled()
    storageFailure.mockRestore()
  })

  it('renders authoritative offline and permission-waiting receipt states', async () => {
    const wrapper = await mountHome()

    await publishCompanionRuntimeEvent({ source: 'health', availability: 'offline' })
    await flushPromises()
    expect(wrapper.text()).toContain('当前离线')
    expect(wrapper.text()).toContain('离线')

    await publishCompanionRuntimeEvent({ source: 'health', availability: 'online' })
    await publishCompanionRuntimeEvent({ source: 'permission', permission: 'waiting', requestId: 'req-42' })
    await flushPromises()
    expect(wrapper.text()).toContain('等待你的确认')
    expect(wrapper.text()).toContain('req-42')
    expect(wrapper.text()).toContain('查看权限回执')

    await publishCompanionRuntimeEvent({ source: 'permission', permission: 'none' })
  })
})

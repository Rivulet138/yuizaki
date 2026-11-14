import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, h, KeepAlive, nextTick, reactive, ref, ssrContextKey, type Ref } from 'vue'
import type { ChatMessage } from '../../../../shared/types'
import ChatPanel from './ChatPanel.vue'

const mocks = vi.hoisted(() => ({
  store: {} as Record<string, unknown>, session: {} as Record<string, unknown>, domain: {} as Record<string, unknown>,
  translate: vi.fn<(text: string) => Promise<string>>(), send: vi.fn(), warning: vi.fn(),
  createSession: vi.fn(), replace: vi.fn(), workspace: {} as { activeWorkspaceId: string },
}))
vi.mock('../composables/useChatDomain', () => ({ useChatDomain: () => ({ ...mocks.domain, inputText: ref('') }) }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => mocks.store }))
vi.mock('@/stores/sessionStore', () => ({ useSessionStore: () => mocks.session }))
vi.mock('@/stores/workspaceStore', () => ({
  isBuiltinWorkPrompt: () => true, isBuiltinDailyPrompt: () => true,
  useWorkspaceStore: () => ({ get activeWorkspaceId() { return mocks.workspace.activeWorkspaceId }, activeWorkspace: { context: {
    promptMode: 'auto', promptEngineering: {}, roleCard: {}, worldBook: {},
  } } }),
}))
vi.mock('@/state/settingsStore', () => ({ useSettingsStore: () => ({ state: { llm: { provider: 'openai', model: 'test-model', base_url: '', api_key: '' }, system: {} }, fetchSettings: async () => undefined }) }))
vi.mock('@/state/inputBindingsStore', () => ({ useInputBindingsStore: () => ({ pushToTalkLabel: ref('Space') }) }))
vi.mock('@/audio/audio-capture', () => ({ enumerateAudioInputDevices: vi.fn() }))
vi.mock('@/api/client', () => ({ settingsClient: { warmupTts: async () => undefined } }))
vi.mock('@/api/clients/memory-client', () => ({ memoryClient: {} }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }), useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string, params?: { content?: string }) => params?.content || key }) }))
vi.mock('element-plus', () => ({ ElMessage: { warning: mocks.warning, success: vi.fn(), error: vi.fn() } }))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('../components/ChatMessageList.vue', () => ({ default: {} }))
vi.mock('../components/SessionRail.vue', () => ({ default: {} }))
vi.mock('../components/ChatPlaybackBar.vue', () => ({ default: {} }))
vi.mock('../components/ChatRuntimeSettings.vue', () => ({ default: {} }))
vi.mock('../components/ChatVoiceStatus.vue', () => ({ default: {} }))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('element-plus/es/components/tooltip/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/dropdown/style/css', () => ({}))
vi.mock('element-plus/es/components/dropdown-item/style/css', () => ({}))
vi.mock('element-plus/es/components/dropdown-menu/style/css', () => ({}))
vi.mock('element-plus/es/components/dialog/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))

interface PanelState {
  inputText: Ref<string>
  handleSendComposer: () => void
}
interface HostNode { parent: HostNode | null; children: HostNode[] }
const node = (): HostNode => ({ parent: null, children: [] })
const remove = (child: HostNode) => {
  if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}
const renderer = createRenderer<HostNode, HostNode>({
  createElement: node, createText: node, createComment: node,
  setText() {}, setElementText() {}, patchProp() {},
  insert(child, parent, anchor) {
    remove(child)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    child.parent = parent
  },
  remove, parentNode: child => child.parent, nextSibling: child => {
    const siblings = child.parent?.children ?? []
    return siblings[siblings.indexOf(child) + 1] ?? null
  },
})
const STORAGE_KEY = 'yuizaki.chat.sessionDrafts.v1'

describe('KeepAlive chat draft ownership', () => {
  let app: ReturnType<typeof renderer.createApp>
  let storage: Map<string, string>
  let states: Map<string, PanelState>
  let visible: Ref<string>
  let chatState: { currentSessionId: string; currentWorkspaceId: string; messages: ChatMessage[]; isGenerating: boolean }
  let session: { activeSessionId: string }
  const persisted = () => JSON.parse(storage.get(STORAGE_KEY) || '{}') as Record<string, string>
  beforeEach(async () => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    storage = new Map()
    states = new Map()
    visible = ref('A')
    vi.stubGlobal('window', Object.assign(new EventTarget(), {
      localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
      setTimeout, clearTimeout,
    }))
    mocks.workspace = reactive({ activeWorkspaceId: 'A' })
    chatState = reactive({ currentSessionId: 'a', currentWorkspaceId: 'A', messages: [], isGenerating: false })
    session = reactive({ activeSessionId: 'a' })
    mocks.session = session
    mocks.domain = { chatState, inputText: ref(''), isRecording: ref(false), socketDomain: { isConnected: ref(true) } }
    mocks.store = {
      chatOptions: reactive({ translation_target: 'en', max_tokens: 256 }), setPromptProfile: vi.fn(), setChatOptions: vi.fn(),
      translateText: mocks.translate, sendChat: mocks.send,
    }
    mocks.send.mockReturnValue(true)
    const Harness = { setup(props: object, context: object) {
      const state = Reflect.apply(Reflect.get(ChatPanel, 'setup'), null, [props, context]) as PanelState
      states.set(visible.value, state)
      return () => h('div')
    } }
    app = renderer.createApp({ setup: () => () => h(KeepAlive, null, { default: () => h(Harness, { key: visible.value }) }) })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(node())
    await nextTick()
  })
  afterEach(() => {
    app.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  const select = async (workspaceId: string, sessionId: string) => {
    mocks.workspace.activeWorkspaceId = workspaceId
    session.activeSessionId = sessionId
    chatState.currentWorkspaceId = workspaceId
    chatState.currentSessionId = sessionId
    visible.value = workspaceId
    await nextTick()
    return states.get(workspaceId)!
  }

  it('keeps B after two cached instances visit A/B/A and the app unmounts', async () => {
    const a = states.get('A')!
    a.inputText.value = 'A draft'
    const b = await select('B', 'b')
    b.inputText.value = 'B draft'
    await select('A', 'a')
    expect(states.size).toBe(2)
    expect(a.inputText.value).toBe('A draft')
    a.inputText.value = 'A revised'
    await vi.advanceTimersByTimeAsync(200)
    expect(persisted()).toEqual({ a: 'A revised', b: 'B draft' })
    app.unmount()
    await vi.advanceTimersByTimeAsync(200)
    expect(persisted()).toEqual({ a: 'A revised', b: 'B draft' })
  })

  it('does not resurrect sent text after a cached instance flushes on unmount', async () => {
    const a = states.get('A')!
    a.inputText.value = 'A draft'
    const b = await select('B', 'b')
    b.inputText.value = 'B draft'
    await select('A', 'a')
    a.handleSendComposer()
    await nextTick()
    app.unmount()
    await vi.advanceTimersByTimeAsync(200)
    expect(persisted()).toEqual({ b: 'B draft' })
  })

  it('separates default drafts when only the workspace changes', async () => {
    const a = await select('A', 'default')
    a.inputText.value = 'A default draft'
    const b = await select('B', 'default')
    expect(b.inputText.value).toBe('')
    b.inputText.value = 'B default draft'
    await select('A', 'default')
    expect(a.inputText.value).toBe('A default draft')
    await select('B', 'default')
    expect(b.inputText.value).toBe('B default draft')
  })

  it('restores a failed default send to its captured workspace after switching', async () => {
    const a = await select('A', 'default')
    a.inputText.value = 'failed A'
    a.handleSendComposer()
    const onFailure = mocks.send.mock.calls[0]?.[1].onFailure as () => void
    const b = await select('B', 'default')
    b.inputText.value = 'B draft'
    onFailure()
    expect(b.inputText.value).toBe('B draft')
    await select('A', 'default')
    expect(a.inputText.value).toBe('failed A')
  })
})

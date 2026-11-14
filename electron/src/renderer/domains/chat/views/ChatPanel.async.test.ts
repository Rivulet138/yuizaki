import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick, reactive, ref, ssrContextKey, type Ref } from 'vue'
import type { ChatAttachment, ChatMessage } from '../../../../shared/types'
import ChatPanel from './ChatPanel.vue'

const mocks = vi.hoisted(() => ({
  store: {} as Record<string, unknown>, session: {} as Record<string, unknown>, domain: {} as Record<string, unknown>,
  translate: vi.fn<(text: string) => Promise<string>>(), send: vi.fn(), warning: vi.fn(),
  confirm: vi.fn(), createSession: vi.fn(), branchSession: vi.fn(), success: vi.fn(), error: vi.fn(), workspace: {} as Record<string, unknown>, replace: vi.fn(), listLlmModels: vi.fn(),
}))
vi.mock('../composables/useChatDomain', () => ({ useChatDomain: () => mocks.domain }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => mocks.store }))
vi.mock('@/stores/sessionStore', () => ({ useSessionStore: () => mocks.session }))
vi.mock('@/stores/workspaceStore', () => ({
  isBuiltinWorkPrompt: () => true, isBuiltinDailyPrompt: () => true,
  useWorkspaceStore: () => mocks.workspace,
}))
vi.mock('@/state/settingsStore', () => ({ useSettingsStore: () => ({ state: reactive({ llm: { provider: 'openai', model: 'test-model', base_url: '', api_key: '' }, system: {} }), fetchSettings: async () => undefined }) }))
vi.mock('@/state/inputBindingsStore', () => ({ useInputBindingsStore: () => ({ pushToTalkLabel: ref('Space') }) }))
vi.mock('@/audio/audio-capture', () => ({ enumerateAudioInputDevices: vi.fn() }))
vi.mock('@/api/client', () => ({ settingsClient: { warmupTts: async () => undefined, listLlmModels: mocks.listLlmModels } }))
vi.mock('@/api/clients/memory-client', () => ({ memoryClient: {} }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }), useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string, params?: { content?: string }) => params?.content || key }) }))
vi.mock('element-plus', () => ({ ElMessageBox: { confirm: mocks.confirm }, ElMessage: { warning: mocks.warning, success: mocks.success, error: mocks.error } }))
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
  refreshModelOptions: (force?: boolean) => Promise<void>
  settingsStore: { state: { llm: { provider: string; base_url: string; api_key: string; timeout: number; model: string } } }
  modelOptions: Ref<string[]>
  modelsLoading: Ref<boolean>
  inputText: Ref<string>
  attachments: Ref<ChatAttachment[]>
  canSendComposer: Ref<boolean>
  translationResult: Ref<string>
  translationDialogVisible: Ref<boolean>
  translationSource: Ref<unknown>
  addFiles: (files: File[]) => Promise<void>
  handleDeleteMsg: (index: number) => Promise<void>
  handleClearConversation: () => Promise<void>
  handleClearContext: () => Promise<void>
  startMessageEdit: (index: number, message: ChatMessage) => void
  saveMessageEdit: (resend: boolean) => Promise<void>
  editingMessage: { index: number; content: string; saving: boolean }
  handleCreateBranch: (index: number, message: ChatMessage) => Promise<void>
  handleSelectSession: (id: string) => Promise<void>
  handleCreateSession: () => Promise<void>
  handleSendComposer: () => void
  translateComposerInput: () => Promise<void>
  handleTranslateMessage: (message: ChatMessage, index: number) => Promise<void>
  applyTranslationToInput: () => void
}
class Reader {
  static pending: Reader[] = []
  result = ''
  error = null
  onload?: () => void
  onerror?: () => void
  onabort?: () => void
  readAsText() { Reader.pending.push(this) }
  abort = vi.fn(() => this.onabort?.())
  finish(text: string) { this.result = text; this.onload?.() }
}
const file = (name = 'notes.txt', type = 'text/plain', size = 10) => ({ name, type, size }) as File

const renderer = createRenderer<object, object>({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, insert() {}, remove() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})

describe('chat panel asynchronous composer ownership', () => {
  let state: PanelState
  let app: ReturnType<typeof renderer.createApp>
  let chatState: { currentSessionId: string; currentWorkspaceId: string; messages: ChatMessage[]; isGenerating: boolean }
  let session: { activeSessionId: string }
  beforeEach(async () => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    Reader.pending = []
    const storage = new Map<string, string>()
    vi.stubGlobal('window', Object.assign(new EventTarget(), {
      localStorage: { getItem: (key: string) => storage.get(key) || null, setItem: (key: string, value: string) => storage.set(key, value) },
      setTimeout, clearTimeout,
    }))
    vi.stubGlobal('FileReader', Reader)
    chatState = reactive({ currentSessionId: 'a', currentWorkspaceId: 'workspace', messages: [], isGenerating: false })
    mocks.workspace = reactive({ activeWorkspaceId: 'workspace', activeWorkspace: { context: {
      promptMode: 'auto', promptEngineering: {}, roleCard: {}, worldBook: {},
    } } })
    session = reactive({ activeSessionId: 'a' })
    mocks.session = Object.assign(session, {
      createSession: mocks.createSession, branchSession: mocks.branchSession,
      sessions: [{ id: 'a', workspace_id: 'workspace' }, { id: 'b', workspace_id: 'workspace' }],
      setActiveSession: (id: string) => { session.activeSessionId = id },
    })
    mocks.domain = { chatState, inputText: ref(''), isRecording: ref(false), socketDomain: { isConnected: ref(true) } }
    mocks.store = {
      chatOptions: reactive({ translation_target: 'en', max_tokens: 256 }), setPromptProfile: vi.fn(), setChatOptions: vi.fn(),
      translateText: mocks.translate, sendChat: mocks.send,
      clearLocalMessages: vi.fn(() => { chatState.messages = [] }), loadHistory: vi.fn(async () => undefined),
      setWorkspaceContext: (workspaceId: string, id: string) => { chatState.currentWorkspaceId = workspaceId; chatState.currentSessionId = id },
    }
    mocks.send.mockReturnValue(true)
    mocks.replace.mockResolvedValue(undefined)
    app = renderer.createApp({ setup(props, context) {
      state = Reflect.apply(Reflect.get(ChatPanel, 'setup'), null, [props, context]) as PanelState
      return () => h('div')
    } })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount({})
    await nextTick()
  })
  afterEach(() => {
    app.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  it.each(['delete', 'clear', 'context'] as const)('does not apply a %s confirmation to a newly selected session', async (action) => {
    let confirm!: () => void
    mocks.confirm.mockReturnValueOnce(new Promise<void>(resolve => { confirm = resolve }))
    mocks.store.deleteMessage = vi.fn()
    mocks.store.clearConversationMessages = vi.fn()
    mocks.store.clearContext = vi.fn()
    chatState.messages = [{ id: 1, role: 'user', content: 'A' }]
    const pending = action === 'delete' ? state.handleDeleteMsg(0)
      : action === 'clear' ? state.handleClearConversation() : state.handleClearContext()
    switchSession('b')
    chatState.messages = [{ id: 2, role: 'user', content: 'B' }]
    confirm()
    await pending
    expect(mocks.store.deleteMessage).not.toHaveBeenCalled()
    expect(mocks.store.clearConversationMessages).not.toHaveBeenCalled()
    expect(mocks.store.clearContext).not.toHaveBeenCalled()
  })

  it('does not resend an old edit or reset the new editor after switching sessions', async () => {
    let resolve!: (value: boolean) => void
    mocks.store.updateMessage = vi.fn(() => new Promise<boolean>(done => { resolve = done }))
    mocks.store.regenerateFromMessage = vi.fn()
    chatState.messages = [{ id: 1, role: 'user', content: 'A' }]
    state.startMessageEdit(0, chatState.messages[0]!)
    state.editingMessage.content = 'A edited'
    const pending = state.saveMessageEdit(true)
    switchSession('b')
    chatState.messages = [{ id: 2, role: 'user', content: 'B' }]
    state.startMessageEdit(0, chatState.messages[0]!)
    state.editingMessage.content = 'B draft'
    resolve(true)
    await pending
    expect(mocks.store.regenerateFromMessage).not.toHaveBeenCalled()
    expect(state.editingMessage).toMatchObject({ index: 0, content: 'B draft', saving: false })
  })

  it.each([true, false])('keeps provider model discovery isolated when an old response resolves first=%s', async (oldFirst) => {
    let resolveOld!: (value: { models: string[] }) => void
    let resolveNew!: (value: { models: string[] }) => void
    mocks.listLlmModels.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    mocks.listLlmModels.mockReturnValueOnce(new Promise((resolve) => { resolveNew = resolve }))
    Object.assign(state.settingsStore.state.llm, { provider: 'chatgpt', base_url: 'https://old.invalid/v1', api_key: 'test', model: 'gpt-4o' })
    await nextTick()
    const oldRequest = state.refreshModelOptions()
    Object.assign(state.settingsStore.state.llm, { provider: 'gemini', base_url: 'https://new.invalid/v1', model: 'gemini-2.5-pro' })
    await nextTick()
    const newRequest = state.refreshModelOptions()
    if (oldFirst) {
      resolveOld({ models: ['old-provider-model'] })
      await oldRequest
      expect(state.modelOptions.value).toEqual([])
      expect(state.modelsLoading.value).toBe(true)
    }
    resolveNew({ models: ['new-provider-model'] })
    await newRequest
    if (!oldFirst) {
      resolveOld({ models: ['old-provider-model'] })
      await oldRequest
    }
    expect(state.modelOptions.value).toEqual(['gemini-2.5-pro', 'new-provider-model'])
    expect(state.modelsLoading.value).toBe(false)
  })
  const switchSession = (id: string) => { session.activeSessionId = id; chatState.currentSessionId = id }

  it('aborts and discards an attachment when a session is left and revisited before reading finishes', async () => {
    const reading = state.addFiles([file()])
    const reader = Reader.pending[0]!
    switchSession('b')
    switchSession('a')
    reader.finish('late A attachment')
    await reading
    expect(reader.abort).toHaveBeenCalled()
    expect(state.attachments.value).toEqual([])
  })

  it('waits for file content before sending and rejects image/binary placeholder payloads', async () => {
    state.inputText.value = 'question'
    const reading = state.addFiles([file(), file('photo.png', 'image/png'), file('archive.bin', 'application/octet-stream')])
    expect(state.canSendComposer.value).toBe(false)
    state.handleSendComposer()
    expect(mocks.send).not.toHaveBeenCalled()
    Reader.pending[0]!.finish('actual file content')
    await reading
    expect(mocks.warning).toHaveBeenCalledTimes(2)
    expect(state.attachments.value).toHaveLength(1)
    state.handleSendComposer()
    expect(mocks.send.mock.calls[0]?.[0]).toContain('actual file content')
  })

  it('discards composer translation after the draft changes even if the original text is restored', async () => {
    let release!: (text: string) => void
    mocks.translate.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    state.inputText.value = 'original'
    const translating = state.translateComposerInput()
    state.inputText.value = 'edited'
    state.inputText.value = 'original'
    release('stale translation')
    await translating
    expect(state.inputText.value).toBe('original')
  })

  it('discards a message translation after the source is edited and prevents applying a result from another session', async () => {
    let release!: (text: string) => void
    mocks.translate.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    chatState.messages.push({ role: 'assistant', content: 'original' })
    const message = chatState.messages[0]!
    const translating = state.handleTranslateMessage(message, 0)
    message.content = 'edited'
    release('stale message translation')
    await translating
    expect(state.translationDialogVisible.value).toBe(false)
    expect(state.translationResult.value).toBe('')
    mocks.translate.mockResolvedValueOnce('valid translation')
    await state.handleTranslateMessage(message, 0)
    expect(state.translationDialogVisible.value).toBe(true)
    switchSession('b')
    state.applyTranslationToInput()
    expect(state.inputText.value).toBe('')
    await nextTick()
  })
  it('restores a failed send alongside newer draft text and attachments in its own session', async () => {
    const sentAttachment: ChatAttachment = { id: 'sent', name: 'notes.txt', type: 'text/plain', size: 4, kind: 'text', content: 'file' }
    const nextAttachment = { ...sentAttachment, id: 'next' }
    state.inputText.value = 'sent draft'
    state.attachments.value = [sentAttachment]
    state.handleSendComposer()
    const onFailure = mocks.send.mock.calls[0]?.[1].onFailure as () => void
    state.inputText.value = 'new draft'
    state.attachments.value = [nextAttachment]
    await nextTick()
    switchSession('b')
    state.inputText.value = 'B draft'
    onFailure()
    expect(state.inputText.value).toBe('B draft')
    switchSession('a')
    expect(state.inputText.value).toBe('sent draft\n\nnew draft')
    expect(state.attachments.value.map(attachment => attachment.id)).toEqual(['sent', 'next'])
  })

  it('activates and routes to a newly created session after the request succeeds', async () => {
    mocks.createSession.mockResolvedValueOnce({ id: 'created' })
    await state.handleCreateSession()
    expect(session.activeSessionId).toBe('created')
    expect(chatState.currentSessionId).toBe('created')
    expect(mocks.replace).toHaveBeenCalledTimes(1)
  })

  it('keeps a newer session selection when an older create request returns', async () => {
    let release!: (value: { id: string }) => void
    mocks.createSession.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const creating = state.handleCreateSession()
    switchSession('b')
    release({ id: 'late-created' })
    await creating
    expect(session.activeSessionId).toBe('b')
    expect(chatState.currentSessionId).toBe('b')
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  const branchMessage: ChatMessage = { id: 42, role: 'assistant', content: 'source' }

  it('explicitly activates a completed branch and loads its route and history', async () => {
    mocks.branchSession.mockResolvedValueOnce({ id: 'branch' })
    chatState.messages = [branchMessage]
    await state.handleCreateBranch(0, branchMessage)
    expect(mocks.branchSession).toHaveBeenCalledWith('a', 42, expect.any(String), 'workspace')
    expect(session.activeSessionId).toBe('branch')
    expect(chatState.currentSessionId).toBe('branch')
    expect(chatState.messages).toEqual([])
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith('/w/workspace/chat/branch')
    expect(mocks.store.loadHistory).toHaveBeenCalledExactlyOnceWith('branch', 'workspace')
    expect(mocks.success).toHaveBeenCalledWith('chat.feedback.branchCreated')
  })

  it.each(['session', 'session round trip', 'workspace', 'workspace round trip', 'unmount'] as const)(
    'discards late branch activation after %s', async (change) => {
      let resolve!: (value: { id: string }) => void
      mocks.branchSession.mockReturnValueOnce(new Promise(resolveBranch => { resolve = resolveBranch }))
      const creating = state.handleCreateBranch(0, branchMessage)
      if (change.startsWith('session')) {
        await state.handleSelectSession('b')
        if (change === 'session round trip') await state.handleSelectSession('a')
      } else if (change.startsWith('workspace')) {
        mocks.workspace.activeWorkspaceId = 'other'
        if (change === 'workspace round trip') mocks.workspace.activeWorkspaceId = 'workspace'
      } else {
        app.unmount()
      }
      const selectedId = session.activeSessionId
      const selectedWorkspaceId = chatState.currentWorkspaceId
      chatState.messages = [{ id: 99, role: 'user', content: 'new target messages' }]
      vi.mocked(mocks.store.clearLocalMessages as ReturnType<typeof vi.fn>).mockClear()
      vi.mocked(mocks.store.loadHistory as ReturnType<typeof vi.fn>).mockClear()
      mocks.replace.mockClear()
      resolve({ id: 'late-branch' })
      await creating
      expect(session.activeSessionId).toBe(selectedId)
      expect(chatState.currentSessionId).toBe(selectedId)
      expect(chatState.currentWorkspaceId).toBe(selectedWorkspaceId)
      expect(chatState.messages[0]?.content).toBe('new target messages')
      expect(mocks.store.clearLocalMessages).not.toHaveBeenCalled()
      expect(mocks.replace).not.toHaveBeenCalled()
      expect(mocks.store.loadHistory).not.toHaveBeenCalled()
      expect(mocks.success).not.toHaveBeenCalled()
    },
  )

  it.each(['selection', 'unmount'] as const)('does not load branch history after a pending route loses ownership through %s', async (change) => {
    let resolve!: () => void
    mocks.branchSession.mockResolvedValueOnce({ id: 'branch' })
    mocks.replace.mockReturnValueOnce(new Promise<void>(done => { resolve = done }))
    const creating = state.handleCreateBranch(0, branchMessage)
    await nextTick()
    expect(mocks.replace).toHaveBeenCalledWith('/w/workspace/chat/branch')
    if (change === 'selection') await state.handleSelectSession('b')
    else app.unmount()
    chatState.messages = [{ id: 99, role: 'user', content: 'current messages' }]
    vi.mocked(mocks.store.loadHistory as ReturnType<typeof vi.fn>).mockClear()
    resolve()
    await creating
    expect(mocks.store.loadHistory).not.toHaveBeenCalled()
    expect(chatState.messages[0]?.content).toBe('current messages')
    expect(mocks.success).not.toHaveBeenCalled()
  })

  it.each(['selection', 'unmount'] as const)('suppresses branch completion feedback after pending history loses ownership through %s', async (change) => {
    let resolve!: () => void
    mocks.branchSession.mockResolvedValueOnce({ id: 'branch' })
    vi.mocked(mocks.store.loadHistory as ReturnType<typeof vi.fn>).mockReturnValueOnce(new Promise<void>(done => { resolve = done }))
    const creating = state.handleCreateBranch(0, branchMessage)
    await nextTick()
    await nextTick()
    expect(mocks.store.loadHistory).toHaveBeenCalledWith('branch', 'workspace')
    if (change === 'selection') await state.handleSelectSession('b')
    else app.unmount()
    mocks.replace.mockClear()
    resolve()
    await creating
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it('suppresses a branch failure after unmount', async () => {
    let reject!: (error: Error) => void
    mocks.branchSession.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    const creating = state.handleCreateBranch(0, branchMessage)
    app.unmount()
    reject(new Error('late failure'))
    await creating
    expect(mocks.error).not.toHaveBeenCalled()
  })

})

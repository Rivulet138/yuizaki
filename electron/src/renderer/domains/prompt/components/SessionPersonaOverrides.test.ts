import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, reactive, type EffectScope, type Ref } from 'vue'
import type { SessionPersonaOverrides, SessionRecord } from '@/stores/sessionStore'
import SessionPersonaOverridesEditor from './SessionPersonaOverrides.vue'

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), sessions: vi.fn() }))
vi.mock('vue', async (original) => ({
  ...await original<typeof import('vue')>(),
  useSSRContext: () => ({ modules: new Set() }), onMounted: vi.fn(), onBeforeUnmount: vi.fn(),
}))
vi.mock('element-plus', () => ({ ElButton: {}, ElInput: {} }))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('@/i18n', () => ({ currentLocale: { value: 'en' }, t: (key: string) => key }))
vi.mock('@/shared/errors/describe-error', () => ({ describeFailure: (error: Error) => error.message }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: mocks.workspace }))
vi.mock('@/stores/sessionStore', () => ({ useSessionStore: mocks.sessions }))

const session = (id: string, workspaceId = 'w', overrides: SessionPersonaOverrides | null = null): SessionRecord => ({
  id, workspace_id: workspaceId, title: id, pinned: false, created_at: null, updated_at: null,
  message_count: 0, total_tokens: 0, persona_overrides: overrides,
})
const workspace = () => reactive({ activeWorkspace: { id: 'w', context: { roleCard: { scenario: 'Workspace scene', exampleDialogue: 'Workspace example' } } } })
const sessions = () => reactive({
  activeSessionId: 'a', sessions: [session('a'), session('b')], loading: false,
  setActiveSession: vi.fn(), loadSessions: vi.fn<() => Promise<void>>(),
  updateSession: vi.fn<(id: string, patch: Partial<SessionRecord>, workspaceId: string) => Promise<SessionRecord>>(),
})
interface State {
  draft: Ref<{ value: SessionPersonaOverrides; base: string }>
  selectedSession: Ref<SessionRecord | undefined>
  dirty: Ref<boolean>; conflict: Ref<boolean>; error: Ref<string>; saving: Ref<boolean>
  toggleOverride: (field: keyof SessionPersonaOverrides, event: Event) => void
  save: () => Promise<void>; restoreInheritance: () => Promise<void>; discardDraft: () => void
  loadSessions: () => Promise<void>
}
let workspaceStore: ReturnType<typeof workspace>
let sessionStore: ReturnType<typeof sessions>
let scope: EffectScope
let state: State
const toggle = (field: keyof SessionPersonaOverrides, checked: boolean) => state.toggleOverride(field, { target: { checked } } as unknown as Event)
const deferred = () => {
  let resolve!: (value: SessionRecord) => void
  const promise = new Promise<SessionRecord>(done => { resolve = done })
  return { resolve, promise }
}
beforeEach(() => {
  vi.resetAllMocks()
  workspaceStore = workspace(); sessionStore = sessions()
  mocks.workspace.mockReturnValue(workspaceStore); mocks.sessions.mockReturnValue(sessionStore)
  sessionStore.setActiveSession.mockImplementation(id => { sessionStore.activeSessionId = id })
  sessionStore.loadSessions.mockResolvedValue(undefined)
  sessionStore.updateSession.mockImplementation(async (id, patch) => {
    const updated = { ...sessionStore.sessions.find(item => item.id === id)!, ...patch }
    sessionStore.sessions = sessionStore.sessions.map(item => item.id === id ? updated : item)
    return updated
  })
  scope = effectScope()
  state = scope.run(() => (SessionPersonaOverridesEditor as any).setup({}, { expose: vi.fn() })) as State
})
afterEach(() => { scope.stop() })

describe('session persona editor ownership and inheritance', () => {
  it('saves explicit empty text while omitted fields continue inheriting', async () => {
    toggle('scenario', true)
    expect(state.draft.value.value.scenario).toBe('Workspace scene')
    state.draft.value.value.scenario = ''
    await state.save()
    expect(sessionStore.updateSession).toHaveBeenCalledExactlyOnceWith('a', { persona_overrides: { scenario: '' } }, 'w')
    expect(state.dirty.value).toBe(false)
    expect(sessionStore.sessions[1]?.persona_overrides).toBeNull()
  })

  it('removes only the unchecked field from the override object', async () => {
    toggle('scenario', true); toggle('exampleDialogue', true); toggle('scenario', false)
    await state.save()
    expect(sessionStore.updateSession).toHaveBeenCalledWith('a', { persona_overrides: { exampleDialogue: 'Workspace example' } }, 'w')
  })

  it('restores inheritance through a null patch and keeps workspace content intact', async () => {
    sessionStore.sessions[0]!.persona_overrides = { scenario: 'Saved scene' }
    await nextTick()
    await state.restoreInheritance()
    expect(sessionStore.updateSession).toHaveBeenCalledExactlyOnceWith('a', { persona_overrides: null }, 'w')
    expect(state.draft.value.value).toEqual({})
    expect(workspaceStore.activeWorkspace.context.roleCard.scenario).toBe('Workspace scene')
  })

  it('keeps a newer draft while a prior save is in flight', async () => {
    toggle('scenario', true)
    const pending = deferred()
    sessionStore.updateSession.mockReturnValueOnce(pending.promise)
    const saving = state.save()
    state.draft.value.value.scenario = 'Typed while saving'
    pending.resolve(session('a', 'w', { scenario: 'Workspace scene' }))
    await saving
    expect(state.draft.value.value.scenario).toBe('Typed while saving')
    expect(state.dirty.value).toBe(true)
  })

  it('routes a late completion to its original session and preserves another draft', async () => {
    toggle('scenario', true)
    const pending = deferred()
    sessionStore.updateSession.mockReturnValueOnce(pending.promise)
    const saving = state.save()
    sessionStore.activeSessionId = 'b'
    toggle('exampleDialogue', true)
    state.draft.value.value.exampleDialogue = 'Session B example'
    pending.resolve(session('a', 'w', { scenario: 'Workspace scene' }))
    await saving
    expect(state.selectedSession.value?.id).toBe('b')
    expect(state.draft.value.value).toEqual({ exampleDialogue: 'Session B example' })
    expect(state.dirty.value).toBe(true)
  })

  it('preserves dirty fields on a remote update and supports explicit draft discard', async () => {
    toggle('scenario', true)
    state.draft.value.value.scenario = 'Unsaved'
    sessionStore.sessions[0]!.persona_overrides = { scenario: 'Remote' }
    await nextTick()
    expect(state.conflict.value).toBe(true)
    expect(state.draft.value.value.scenario).toBe('Unsaved')
    state.discardDraft()
    expect(state.draft.value.value.scenario).toBe('Remote')
    expect(state.dirty.value).toBe(false)
  })

  it('does not edit a session owned by another workspace', async () => {
    workspaceStore.activeWorkspace.id = 'other'
    await state.save()
    expect(state.selectedSession.value).toBeUndefined()
    expect(sessionStore.updateSession).not.toHaveBeenCalled()
    await nextTick()
  })

  it('retains failed saves for retry', async () => {
    toggle('scenario', true)
    sessionStore.updateSession.mockRejectedValueOnce(new Error('Save rejected'))
    await state.save()
    expect(state.error.value).toBe('Save rejected')
    expect(state.saving.value).toBe(false)
    expect(state.dirty.value).toBe(true)
    await state.save()
    expect(state.error.value).toBe('')
    expect(state.dirty.value).toBe(false)
  })

  it('reports session loading failures', async () => {
    sessionStore.loadSessions.mockRejectedValueOnce(new Error('Load rejected'))
    await state.loadSessions()
    expect(state.error.value).toBe('Load rejected')
  })
})

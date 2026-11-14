import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, reactive, type EffectScope, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import PromptPanel from './PromptPanel.vue'

const mocks = vi.hoisted(() => ({
  workspaceStore: vi.fn(),
  companionStore: vi.fn(),
  applyActiveCompanionRuntime: vi.fn(),
}))

vi.mock('vue', async (original) => ({
  ...await original<typeof import('vue')>(),
  useSSRContext: () => ({ modules: new Set() }),
  onMounted: vi.fn(),
  onBeforeUnmount: vi.fn(),
}))
vi.mock('element-plus', () => ({
  ElButton: {},
  ElInput: {},
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('@/shared/components/prompt/WorkspacePromptEditor.vue', () => ({ default: {} }))
vi.mock('@/i18n', () => ({ currentLocale: { value: 'en' }, t: (key: string) => key }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: mocks.workspaceStore }))
vi.mock('@/stores/companionStore', () => ({ useCompanionStore: mocks.companionStore }))
vi.mock('@/app/composables/useCompanionRuntimeBridge', () => ({
  useCompanionRuntimeBridge: () => ({ applyActiveCompanionRuntime: mocks.applyActiveCompanionRuntime }),
}))

interface Workspace {
  id: string
  name: string
  system_prompt: string | null
}
interface Companion {
  id: string
  name: string
  persona_prompt: string | null
}
interface PromptState {
  workspaceSystemPrompt: Ref<string>
  companionPersonaPrompt: Ref<string>
  workspacePromptDirty: Ref<boolean>
  companionPromptDirty: Ref<boolean>
  workspaceConflict: Ref<boolean>
  companionConflict: Ref<boolean>
  savingWorkspacePrompt: Ref<boolean>
  savingCompanionPrompt: Ref<boolean>
  saveWorkspaceSystemPrompt: () => Promise<void>
  saveCompanionPersonaPrompt: () => Promise<void>
  resetWorkspaceDraft: () => void
  resetCompanionDraft: () => void
  loadCompanions: () => Promise<void>
}

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const makeWorkspace = (id: string, text: string): Workspace => ({ id, name: id, system_prompt: text })
const makeCompanion = (id: string, text: string): Companion => ({ id, name: id, persona_prompt: text })

const createWorkspaceStore = () => reactive({
  activeWorkspaceId: 'a',
  workspaces: [makeWorkspace('a', 'workspace A saved'), makeWorkspace('b', 'workspace B saved')],
  get activeWorkspace(): Workspace {
    return this.workspaces.find((record) => record.id === this.activeWorkspaceId)!
  },
  updateWorkspaceRemote: vi.fn<(id: string, patch: { system_prompt: string | null }) => Promise<Workspace>>(),
})
const createCompanionStore = () => reactive({
  activeCompanionId: 'a',
  companions: [makeCompanion('a', 'companion A saved'), makeCompanion('b', 'companion B saved')],
  loading: false,
  get activeCompanion(): Companion | null {
    return this.companions.find((record) => record.id === this.activeCompanionId) ?? null
  },
  updateCompanion: vi.fn<(id: string, patch: { persona_prompt: string | null }) => Promise<Companion>>(),
  loadCompanions: vi.fn<() => Promise<void>>(),
})
let workspaceStore: ReturnType<typeof createWorkspaceStore>
let companionStore: ReturnType<typeof createCompanionStore>
let scope: EffectScope
let state: PromptState

type Kind = 'workspace' | 'companion'
const lane = (kind: Kind) => kind === 'workspace' ? {
  prompt: state.workspaceSystemPrompt,
  dirty: state.workspacePromptDirty,
  conflict: state.workspaceConflict,
  saving: state.savingWorkspacePrompt,
  save: state.saveWorkspaceSystemPrompt,
  reset: state.resetWorkspaceDraft,
  select: (id: string) => { workspaceStore.activeWorkspaceId = id },
  refresh: async (text: string) => {
    workspaceStore.workspaces = workspaceStore.workspaces.map((record) => record.id === 'a' ? { ...record, system_prompt: text } : record)
  },
} : {
  prompt: state.companionPersonaPrompt,
  dirty: state.companionPromptDirty,
  conflict: state.companionConflict,
  saving: state.savingCompanionPrompt,
  save: state.saveCompanionPersonaPrompt,
  reset: state.resetCompanionDraft,
  select: (id: string) => { companionStore.activeCompanionId = id },
  refresh: async (text: string) => {
    companionStore.loadCompanions.mockImplementationOnce(async () => {
      companionStore.companions = companionStore.companions.map((record) => record.id === 'a' ? { ...record, persona_prompt: text } : record)
    })
    await state.loadCompanions()
  },
}

// Model the real stores: replace the saved record before the action resolves,
// so the component's synchronous remote watchers run before its save continuation.
const holdSave = (kind: Kind) => {
  const response = deferred<string>()
  if (kind === 'workspace') {
    workspaceStore.updateWorkspaceRemote.mockImplementationOnce(async (id) => {
      const saved = makeWorkspace(id, await response.promise)
      workspaceStore.workspaces = workspaceStore.workspaces.map((record) => record.id === id ? saved : record)
      return saved
    })
  } else {
    companionStore.updateCompanion.mockImplementationOnce(async (id) => {
      const saved = makeCompanion(id, await response.promise)
      companionStore.companions = companionStore.companions.map((record) => record.id === id ? saved : record)
      return saved
    })
  }
  return response
}
const expectSubmission = (kind: Kind, text: string | null) => {
  if (kind === 'workspace') expect(workspaceStore.updateWorkspaceRemote).toHaveBeenCalledExactlyOnceWith('a', { system_prompt: text })
  else expect(companionStore.updateCompanion).toHaveBeenCalledExactlyOnceWith('a', { persona_prompt: text })
}

beforeEach(() => {
  vi.resetAllMocks()
  workspaceStore = createWorkspaceStore()
  companionStore = createCompanionStore()
  mocks.workspaceStore.mockReturnValue(workspaceStore)
  mocks.companionStore.mockReturnValue(companionStore)
  mocks.applyActiveCompanionRuntime.mockResolvedValue(undefined)
  companionStore.loadCompanions.mockResolvedValue(undefined)
  scope = effectScope()
  // Same real SFC setupState technique as SettingsPanel.regression.test.ts;
  // retain Vue's refs, computed values and watchers without mounting a DOM.
  state = scope.run(() => (PromptPanel as any).setup({}, { expose: vi.fn() })) as PromptState
})
afterEach(() => { scope.stop() })

describe.each(['workspace', 'companion'] as const)('%s prompt draft regression', (kind) => {
  it('accepts remote refreshes for a clean draft, but preserves local edits on later refreshes', async () => {
    const editor = lane(kind)
    await editor.refresh('remote baseline')
    expect(editor.prompt.value).toBe('remote baseline')
    expect(editor.dirty.value).toBe(false)
    expect(editor.conflict.value).toBe(false)

    editor.prompt.value = 'unsaved local draft'
    await editor.refresh('remote changed again')
    expect(editor.prompt.value).toBe('unsaved local draft')
    expect(editor.dirty.value).toBe(true)
    expect(editor.conflict.value).toBe(true)
    if (kind === 'companion') expect(companionStore.loadCompanions).toHaveBeenCalledTimes(2)

    editor.reset()
    expect(editor.prompt.value).toBe('remote changed again')
    expect(editor.dirty.value).toBe(false)
    expect(editor.conflict.value).toBe(false)
  })

  it('keeps separate drafts by ID and restores them across repeated switches', () => {
    const editor = lane(kind)
    editor.prompt.value = 'A local draft'
    editor.select('b')
    expect(editor.prompt.value).toBe(`${kind} B saved`)
    expect(editor.dirty.value).toBe(false)
    editor.prompt.value = 'B local draft'
    editor.select('a')
    expect(editor.prompt.value).toBe('A local draft')
    expect(editor.dirty.value).toBe(true)
    editor.select('b')
    expect(editor.prompt.value).toBe('B local draft')
    expect(editor.dirty.value).toBe(true)
    // Both stores intentionally use the same IDs: their caches must also be separate.
    const otherKind = kind === 'workspace' ? 'companion' : 'workspace'
    expect(lane(otherKind).prompt.value).toBe(`${otherKind} A saved`)
  })

  it('preserves newer input while committing the normalized response as the saved baseline', async () => {
    const editor = lane(kind)
    const response = holdSave(kind)
    editor.prompt.value = '  submitted draft  '
    const saving = editor.save()
    expect(editor.saving.value).toBe(true)
    expectSubmission(kind, 'submitted draft')
    editor.prompt.value = 'newer unsaved input'
    response.resolve('server normalized submission')
    await saving

    expect(editor.prompt.value).toBe('newer unsaved input')
    expect(editor.dirty.value).toBe(true)
    expect(editor.conflict.value).toBe(false)
    expect(editor.saving.value).toBe(false)
    editor.prompt.value = 'server normalized submission'
    expect(editor.dirty.value).toBe(false)
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('uses the normalized saved text when there was no newer input', async () => {
    const editor = lane(kind)
    const response = holdSave(kind)
    editor.prompt.value = '  submitted draft  '
    const saving = editor.save()
    expectSubmission(kind, 'submitted draft')
    response.resolve('normalized text')
    await saving
    expect(editor.prompt.value).toBe('normalized text')
    expect(editor.dirty.value).toBe(false)
    expect(editor.conflict.value).toBe(false)
    if (kind === 'companion') expect(mocks.applyActiveCompanionRuntime).toHaveBeenCalledOnce()
  })

  it('lets another selected editor save while the original request remains pending', async () => {
    const editor = lane(kind)
    const response = holdSave(kind)
    editor.prompt.value = 'A pending draft'
    const savingA = editor.save()
    editor.select('b')
    editor.prompt.value = 'B submitted draft'
    expect(editor.saving.value).toBe(false)
    if (kind === 'workspace') workspaceStore.updateWorkspaceRemote.mockResolvedValueOnce(makeWorkspace('b', 'B submitted draft'))
    else companionStore.updateCompanion.mockResolvedValueOnce(makeCompanion('b', 'B submitted draft'))
    await editor.save()
    expect(editor.dirty.value).toBe(false)
    editor.select('a')
    expect(editor.saving.value).toBe(true)
    response.resolve('A pending draft')
    await savingA
    expect(editor.saving.value).toBe(false)
  })

  it('commits an in-flight save only to the original ID after switching editors', async () => {
    const editor = lane(kind)
    const response = holdSave(kind)
    editor.prompt.value = 'A submitted draft'
    const saving = editor.save()
    expectSubmission(kind, 'A submitted draft')
    editor.select('b')
    editor.prompt.value = 'B unsaved draft'
    response.resolve('A normalized saved text')
    await saving

    expect(editor.prompt.value).toBe('B unsaved draft')
    expect(editor.dirty.value).toBe(true)
    expect(editor.conflict.value).toBe(false)
    expect(editor.saving.value).toBe(false)
    expect(mocks.applyActiveCompanionRuntime).not.toHaveBeenCalled()
    editor.select('a')
    expect(editor.prompt.value).toBe('A normalized saved text')
    expect(editor.dirty.value).toBe(false)
  })

  it('retains the original baseline and newer draft when saving fails, and allows retry', async () => {
    const editor = lane(kind)
    const response = holdSave(kind)
    editor.prompt.value = 'failed submission'
    const saving = editor.save()
    editor.prompt.value = 'draft edited while saving'
    response.reject(new Error('save failed'))
    await saving

    expect(editor.prompt.value).toBe('draft edited while saving')
    expect(editor.dirty.value).toBe(true)
    expect(editor.conflict.value).toBe(false)
    expect(editor.saving.value).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledExactlyOnceWith(`promptPanel.${kind}.saveFailed`)
    expect(mocks.applyActiveCompanionRuntime).not.toHaveBeenCalled()
    editor.prompt.value = `${kind} A saved`
    expect(editor.dirty.value).toBe(false)

    editor.prompt.value = 'retry draft'
    const retry = holdSave(kind)
    const retrying = editor.save()
    retry.resolve('retry saved')
    await retrying
    expect(editor.prompt.value).toBe('retry saved')
    expect(editor.dirty.value).toBe(false)
  })
})

describe('companion save runtime selection boundary', () => {
  it('does not apply a completed save to the companion in a newly selected workspace', async () => {
    const response = holdSave('companion')
    state.companionPersonaPrompt.value = 'A submitted persona'
    const saving = state.saveCompanionPersonaPrompt()
    expectSubmission('companion', 'A submitted persona')
    workspaceStore.activeWorkspaceId = 'b'
    response.resolve('A saved persona')
    await saving

    expect(mocks.applyActiveCompanionRuntime).not.toHaveBeenCalled()
    expect(state.companionPersonaPrompt.value).toBe('A saved persona')
    expect(state.companionPromptDirty.value).toBe(false)
    expect(state.savingCompanionPrompt.value).toBe(false)
    expect(companionStore.activeCompanionId).toBe('a')
    expect(workspaceStore.activeWorkspaceId).toBe('b')
  })
})

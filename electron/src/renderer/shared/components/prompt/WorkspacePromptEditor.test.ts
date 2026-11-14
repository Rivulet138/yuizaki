import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, reactive, type EffectScope, type Ref } from 'vue'
import type { WorkspaceContext, WorkspacePromptEngineering, WorkspaceRoleCard, WorkspaceWorldBook } from '../../../../shared/workspace'
import { exportCharacterCard } from '@/domains/prompt/character-card'
import WorkspacePromptEditor from './WorkspacePromptEditor.vue'

const mocks = vi.hoisted(() => ({ useWorkspaceStore: vi.fn() }))
vi.mock('vue', async (original) => ({
  ...await original<typeof import('vue')>(),
  useSSRContext: () => ({ modules: new Set() }),
}))
vi.mock('element-plus', () => ({
  ElEmpty: {}, ElButton: {}, ElCheckbox: {}, ElSwitch: {}, ElInputNumber: {}, ElInput: {}, ElForm: {}, ElFormItem: {},
}))
vi.mock('element-plus/es/components/empty/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/checkbox/style/css', () => ({}))
vi.mock('element-plus/es/components/switch/style/css', () => ({}))
vi.mock('element-plus/es/components/input-number/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('element-plus/es/components/form/style/css', () => ({}))
vi.mock('element-plus/es/components/form-item/style/css', () => ({}))
vi.mock('@/i18n', () => ({ currentLocale: { value: 'en' }, t: (key: string) => key }))
vi.mock('@/stores/workspaceStore', () => ({
  useWorkspaceStore: mocks.useWorkspaceStore,
  defaultWorkPrompt: () => 'default work',
  defaultDailyPrompt: () => 'default daily',
  isBuiltinWorkPrompt: (value: string) => value === 'default work',
  isBuiltinDailyPrompt: (value: string) => value === 'default daily',
}))

type PromptContext = Pick<WorkspaceContext, 'promptMode' | 'promptEngineering' | 'roleCard' | 'worldBook'>
interface EditorState {
  roleCardModel: WorkspaceRoleCard
  roleCardJson: Ref<string>
  roleCardJsonError: Ref<string>
  roleCardJsonDirty: Ref<boolean>
  promptEngineeringModel: WorkspacePromptEngineering
  worldBookModel: WorkspaceWorldBook
  worldBookJson: Ref<string>
  worldBookJsonError: Ref<string>
  applyRoleCardJson: (text: string) => void
  importRoleCardFile: (event: Event) => Promise<void>
  addGreeting: () => void
  removeGreeting: (index: number) => void
  moveGreeting: (index: number, delta: number) => void
}
const makeContext = (id: string): PromptContext => ({
  promptMode: 'auto',
  promptEngineering: { workPrompt: `${id} work`, dailyPrompt: `${id} daily` },
  roleCard: {
    enabled: true, name: `${id} name`, description: `${id} background`, personality: `${id} personality`,
    scenario: `${id} scenario`, instructions: `${id} instructions`, firstMessage: `${id} greeting`,
    exampleDialogue: `${id} example dialogue`, alternateGreetings: [], greetingIndex: -1, sourceCard: undefined,
  },
  worldBook: {
    enabled: true, scanDepth: 8, maxEntries: 8, budgetTokens: 1200,
    entries: [{
      id: `${id}-entry`, title: `${id} title`, keys: [id], secondaryKeys: [], content: `${id} lore`,
      enabled: true, priority: 0, insertionOrder: 0, constant: false, selective: false,
      caseSensitive: false, matchWholeWords: false, probability: 100,
    }],
  },
})
const createStore = () => reactive({
  activeWorkspaceId: 'a',
  workspaces: [{ id: 'a', context: makeContext('a') }, { id: 'b', context: makeContext('b') }],
  get activeWorkspace(): { id: string; context: PromptContext } {
    return this.workspaces.find((workspace) => workspace.id === this.activeWorkspaceId)!
  },
  updateWorkspaceContext: vi.fn<(id: string, patch: Partial<PromptContext>) => void>(),
})
let store: ReturnType<typeof createStore>
let scope: EffectScope
let state: EditorState
const editJson = (text: string) => {
  // Reproduce the textarea v-model and its @input handler, without a DOM.
  state.roleCardJson.value = text
  state.roleCardJsonDirty.value = true
}

beforeEach(async () => {
  vi.resetAllMocks()
  store = createStore()
  store.updateWorkspaceContext.mockImplementation((id, patch) => {
    const workspace = store.workspaces.find((record) => record.id === id)!
    // Match the real store's top-level context merge, including reactive feedback.
    workspace.context = { ...workspace.context, ...patch }
  })
  mocks.useWorkspaceStore.mockReturnValue(store)
  scope = effectScope()
  state = scope.run(() => (WorkspacePromptEditor as any).setup(
    { showMode: true, dense: false, section: 'all' }, { expose: vi.fn() },
  )) as EditorState
  // Let the real initial nextTick release the component's synchronization guard.
  await nextTick()
  expect(store.updateWorkspaceContext).not.toHaveBeenCalled()
})
afterEach(() => { scope.stop() })

describe('workspace prompt editor setup regression', () => {
  it('hydrates and persists structured background and example dialogue without losing other role fields', async () => {
    expect(state.roleCardModel).toEqual(makeContext('a').roleCard)
    state.roleCardModel.description = 'Revised identity and background'
    state.roleCardModel.exampleDialogue = 'User: Hello\nCharacter: Welcome back.'
    await nextTick()

    const expected = {
      ...makeContext('a').roleCard,
      description: 'Revised identity and background',
      exampleDialogue: 'User: Hello\nCharacter: Welcome back.',
    }
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', { roleCard: expected })
    expect(store.activeWorkspace.context.roleCard).toEqual(expected)
    expect(JSON.parse(state.roleCardJson.value).data).toMatchObject({
      description: expected.description, mes_example: expected.exampleDialogue,
    })
  })

  it('keeps the effective character card intact when explicitly applying invalid JSON or an invalid card shape', async () => {
    for (const text of ['{"description":', '[]', '{"name":42}']) {
      editJson(text)
      state.applyRoleCardJson(state.roleCardJson.value)
      await nextTick()

      expect(state.roleCardJsonError.value).not.toBe('')
      expect(state.roleCardJson.value).toBe(text)
      expect(state.roleCardJsonDirty.value).toBe(true)
      expect(state.roleCardModel).toEqual(makeContext('a').roleCard)
      expect(store.activeWorkspace.context.roleCard).toEqual(makeContext('a').roleCard)
      expect(store.updateWorkspaceContext).not.toHaveBeenCalled()
    }
  })

  it('persists world book and behavior edits independently while an invalid JSON draft remains', async () => {
    editJson('{broken draft')
    state.applyRoleCardJson(state.roleCardJson.value)
    await nextTick()
    state.worldBookModel.budgetTokens = 2400
    state.worldBookModel.entries[0]!.content = 'new independent lore'
    await nextTick()
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', {
      worldBook: { ...makeContext('a').worldBook, budgetTokens: 2400, entries: [
        { ...makeContext('a').worldBook.entries[0]!, content: 'new independent lore' },
      ] },
    })

    store.updateWorkspaceContext.mockClear()
    state.promptEngineeringModel.workPrompt = 'new independent work prompt'
    await nextTick()
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', {
      promptEngineering: { workPrompt: 'new independent work prompt', dailyPrompt: 'a daily' },
    })
    expect(store.activeWorkspace.context.worldBook.entries[0]!.content).toBe('new independent lore')
    expect(store.activeWorkspace.context.roleCard).toEqual(makeContext('a').roleCard)
    expect(state.roleCardJson.value).toBe('{broken draft')
    expect(state.roleCardJsonDirty.value).toBe(true)
    expect(state.roleCardJsonError.value).not.toBe('')
  })

  it('applies JSON only on explicit apply and preserves pending JSON through structured edits', async () => {
    const imported = { ...makeContext('imported').roleCard, description: 'JSON background', exampleDialogue: 'JSON dialogue' }
    const text = JSON.stringify(exportCharacterCard(imported))
    editJson(text)
    await nextTick()
    expect(state.roleCardModel).toEqual(makeContext('a').roleCard)
    expect(store.updateWorkspaceContext).not.toHaveBeenCalled()

    state.roleCardModel.description = 'structured background before apply'
    await nextTick()
    expect(store.activeWorkspace.context.roleCard.description).toBe('structured background before apply')
    expect(state.roleCardJson.value).toBe(text)
    expect(state.roleCardJsonDirty.value).toBe(true)

    store.updateWorkspaceContext.mockClear()
    state.applyRoleCardJson(state.roleCardJson.value)
    await nextTick()
    const expectedImported = { ...imported, sourceCard: JSON.parse(text) }
    expect(state.roleCardModel).toEqual(expectedImported)
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', { roleCard: expectedImported })
    expect(state.roleCardJsonDirty.value).toBe(false)
    expect(state.roleCardJsonError.value).toBe('')
    expect(JSON.parse(state.roleCardJson.value)).toEqual(exportCharacterCard(imported))
  })

  it('sends only the edited section so stale neighboring models cannot overwrite newer stored sections', async () => {
    const remoteRole = { ...makeContext('a').roleCard, description: 'new remote background' }
    const remoteWorld = { ...makeContext('a').worldBook, budgetTokens: 9000 }
    store.activeWorkspace.context.roleCard = remoteRole
    store.activeWorkspace.context.worldBook = remoteWorld
    state.promptEngineeringModel.dailyPrompt = 'edited behavior'
    await nextTick()
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', {
      promptEngineering: { workPrompt: 'a work', dailyPrompt: 'edited behavior' },
    })
    expect(store.activeWorkspace.context.roleCard).toEqual(remoteRole)
    expect(store.activeWorkspace.context.worldBook).toEqual(remoteWorld)

    store.updateWorkspaceContext.mockClear()
    state.roleCardModel.name = 'edited structured name'
    await nextTick()
    const editedRole = { ...makeContext('a').roleCard, name: 'edited structured name' }
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', { roleCard: editedRole })
    expect(store.activeWorkspace.context.worldBook).toEqual(remoteWorld)
    expect(store.activeWorkspace.context.promptEngineering.dailyPrompt).toBe('edited behavior')

    store.updateWorkspaceContext.mockClear()
    store.activeWorkspace.context.roleCard = remoteRole
    state.worldBookModel.scanDepth = 12
    await nextTick()
    expect(store.updateWorkspaceContext).toHaveBeenCalledExactlyOnceWith('a', {
      worldBook: { ...makeContext('a').worldBook, scanDepth: 12 },
    })
    expect(store.activeWorkspace.context.roleCard).toEqual(remoteRole)
    expect(store.activeWorkspace.context.promptEngineering.dailyPrompt).toBe('edited behavior')
  })

  it('hydrates each workspace without persisting fields or pending JSON from the previous selection', async () => {
    state.roleCardModel.description = 'a edited background'
    state.roleCardModel.exampleDialogue = 'a edited dialogue'
    state.worldBookModel.entries[0]!.content = 'a edited lore'
    state.promptEngineeringModel.workPrompt = 'a edited work'
    await nextTick()
    const savedA = {
      ...makeContext('a'),
      roleCard: { ...makeContext('a').roleCard, description: 'a edited background', exampleDialogue: 'a edited dialogue' },
      worldBook: { ...makeContext('a').worldBook, entries: [{ ...makeContext('a').worldBook.entries[0]!, content: 'a edited lore' }] },
      promptEngineering: { workPrompt: 'a edited work', dailyPrompt: 'a daily' },
    }
    editJson('{unsaved a JSON')
    state.applyRoleCardJson(state.roleCardJson.value)
    state.worldBookJson.value = 'a world book draft'
    state.worldBookJsonError.value = 'a world book error'
    store.updateWorkspaceContext.mockClear()
    store.activeWorkspaceId = 'b'
    await nextTick()

    expect(store.updateWorkspaceContext).not.toHaveBeenCalled()
    expect(state.roleCardModel).toEqual(makeContext('b').roleCard)
    expect(state.worldBookModel).toEqual(makeContext('b').worldBook)
    expect(state.promptEngineeringModel).toEqual(makeContext('b').promptEngineering)
    expect(JSON.parse(state.roleCardJson.value)).toEqual(exportCharacterCard(makeContext('b').roleCard))
    expect(state.roleCardJsonDirty.value).toBe(false)
    expect(state.roleCardJsonError.value).toBe('')
    expect(state.worldBookJson.value).toBe('')
    expect(state.worldBookJsonError.value).toBe('')

    state.roleCardModel.description = 'b edited background'
    state.worldBookModel.budgetTokens = 3600
    state.promptEngineeringModel.dailyPrompt = 'b edited daily'
    await nextTick()
    expect(store.updateWorkspaceContext).toHaveBeenCalledTimes(3)
    expect(store.updateWorkspaceContext.mock.calls.every(([id]) => id === 'b')).toBe(true)
    expect(store.workspaces[0]!.context).toEqual(savedA)

    store.updateWorkspaceContext.mockClear()
    store.activeWorkspaceId = 'a'
    await nextTick()
    expect(store.updateWorkspaceContext).not.toHaveBeenCalled()
    expect(state.roleCardModel).toEqual(savedA.roleCard)
    expect(state.worldBookModel).toEqual(savedA.worldBook)
    expect(state.promptEngineeringModel).toEqual(savedA.promptEngineering)
  })

  it('round-trips a V2 export through applyRoleCardJson including background, dialogue and local world book extensions', async () => {
    const original = makeContext('exported')
    original.roleCard.description = 'Exported background with personal history'
    original.roleCard.exampleDialogue = 'User: Ready?\nCharacter: Always.'
    original.worldBook.enabled = false
    original.worldBook.maxEntries = 17
    original.worldBook.entries[0]!.id = 'stable-exported-entry-id'
    original.worldBook.entries[0]!.probability = 37
    original.worldBook.entries[0]!.matchWholeWords = true
    const exported = exportCharacterCard(original.roleCard, original.worldBook)
    expect(exported.spec).toBe('chara_card_v2')
    expect(exported.data.character_book!.extensions.yuizaki).toEqual({ enabled: false, maxEntries: 17 })
    expect(exported.data.character_book!.entries[0]!.extensions.yuizaki).toEqual({
      id: 'stable-exported-entry-id', probability: 37, matchWholeWords: true,
    })

    // Import into an empty book so this exercises replacement rather than merge.
    state.worldBookModel.entries = []
    await nextTick()
    store.updateWorkspaceContext.mockClear()
    editJson(JSON.stringify(exported))
    state.applyRoleCardJson(state.roleCardJson.value)
    await nextTick()

    expect(state.roleCardJsonError.value).toBe('')
    const importedRole = { ...original.roleCard, sourceCard: exportCharacterCard(original.roleCard, original.worldBook) }
    expect(state.roleCardModel).toEqual(importedRole)
    expect(state.worldBookModel).toEqual(original.worldBook)
    expect(store.activeWorkspace.context.roleCard).toEqual(importedRole)
    expect(store.activeWorkspace.context.worldBook).toEqual(original.worldBook)
    expect(store.updateWorkspaceContext).toHaveBeenCalledTimes(2)
    expect(store.updateWorkspaceContext).toHaveBeenCalledWith('a', { roleCard: importedRole })
    expect(store.updateWorkspaceContext).toHaveBeenCalledWith('a', { worldBook: original.worldBook })
  })

  it('discards an asynchronous role-card file result after switching workspaces', async () => {
    let resolve!: (text: string) => void
    const reading = new Promise<string>((done) => { resolve = done })
    const input = { files: [{ text: vi.fn(() => reading) }], value: 'a-character.json' }
    const importing = state.importRoleCardFile({ target: input } as unknown as Event)
    expect(input.files[0]!.text).toHaveBeenCalledOnce()
    store.activeWorkspaceId = 'b'
    await nextTick()
    resolve(JSON.stringify(exportCharacterCard(makeContext('late-a-file').roleCard)))
    await importing
    await nextTick()

    expect(store.updateWorkspaceContext).not.toHaveBeenCalled()
    expect(state.roleCardModel).toEqual(makeContext('b').roleCard)
    expect(store.activeWorkspace.context).toEqual(makeContext('b'))
    expect(store.workspaces[0]!.context).toEqual(makeContext('a'))
    expect(JSON.parse(state.roleCardJson.value)).toEqual(exportCharacterCard(makeContext('b').roleCard))
    expect(state.roleCardJsonDirty.value).toBe(false)
    expect(state.roleCardJsonError.value).toBe('')
    expect(input.value).toBe('')
  })
})


describe('alternate greeting edits', () => {
  it('preserves the selected greeting when reordering and removing preceding rows', async () => {
    state.roleCardModel.alternateGreetings = ['First', 'Second', 'Third']
    state.roleCardModel.greetingIndex = 1
    state.moveGreeting(1, -1)
    expect(state.roleCardModel.alternateGreetings).toEqual(['Second', 'First', 'Third'])
    expect(state.roleCardModel.greetingIndex).toBe(0)
    state.moveGreeting(0, 1)
    state.removeGreeting(0)
    expect(state.roleCardModel.alternateGreetings).toEqual(['Second', 'Third'])
    expect(state.roleCardModel.greetingIndex).toBe(0)
    await nextTick()
    expect(store.activeWorkspace.context.roleCard.alternateGreetings).toEqual(['Second', 'Third'])
  })

  it('falls back to the main greeting when the selected alternative is removed', () => {
    state.addGreeting()
    state.roleCardModel.greetingIndex = 0
    state.removeGreeting(0)
    expect(state.roleCardModel.greetingIndex).toBe(-1)
    expect(state.roleCardModel.alternateGreetings).toEqual([])
  })
})

import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkspaceApiRecord, WorkspacePatchPayload } from '@/api/clients/workspace-client'
import { useWorkspaceStore } from './workspaceStore'
import { cloneRoleCard, createEmptyRoleCard, exportCharacterCard, getRoleCardGreeting, parseCharacterCard } from '../domains/prompt/character-card'

const mocks = vi.hoisted(() => ({ update: vi.fn<(id: string, patch: WorkspacePatchPayload) => Promise<WorkspaceApiRecord>>() }))
vi.mock('@/api/clients/workspace-client', () => ({ workspaceClient: { update: mocks.update } }))
vi.mock('./companionStore', () => ({ useCompanionStore: () => ({ activeCompanionId: 'companion' }) }))
vi.mock('@/i18n', async () => {
  const { ref } = await import('vue')
  return { currentLocale: ref('zh-CN'), localeTables: {}, t: (key: string) => key }
})
const response = (patch: WorkspacePatchPayload, revision: number): WorkspaceApiRecord => ({
  id: 'default', name: 'default', created_at: null, updated_at: null, context: patch.context, contextRevision: revision,
})
const conflict = (revision: number) => ({ status: 409, payload: { context: { activeTab: 'server', heroHeight: 440 }, contextRevision: revision } })

// Exercise the actual store and timer queue, including edits made while the request is in flight.
describe('workspace save concurrency', () => {
  let pinia: ReturnType<typeof createPinia>
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.update.mockReset()
    pinia = createPinia()
    setActivePinia(pinia)
    const storage = new Map<string, string>()
    vi.stubGlobal('window', {
      localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
      setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout,
    })
  })
  afterEach(() => { disposePinia(pinia); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it('rebases all coalesced edits once and preserves unrelated server fields', async () => {
    mocks.update.mockRejectedValueOnce(conflict(3)).mockImplementation(async (_id, patch) => response(patch, 4))
    const store = useWorkspaceStore()
    store.updateWorkspaceContext('default', { activeTab: 'tools' })
    store.updateWorkspaceContext('default', { layoutPreset: 'wide' })
    await vi.advanceTimersByTimeAsync(600)
    expect(mocks.update).toHaveBeenCalledTimes(2)
    expect(mocks.update.mock.calls[1]?.[1]).toMatchObject({ contextRevision: 3, context: { activeTab: 'tools', layoutPreset: 'wide', heroHeight: 440 } })
    expect(store.contextSaveStatus.default).toBe('saved')
  })

  it('serializes a newer input behind an in-flight save without reverting the draft', async () => {
    let finish!: (value: WorkspaceApiRecord) => void
    mocks.update.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockImplementation(async (_id, patch) => response(patch, 2))
    const store = useWorkspaceStore()
    store.updateWorkspaceContext('default', { activeTab: 'tools' })
    await vi.advanceTimersByTimeAsync(600)
    store.updateWorkspaceContext('default', { activeTab: 'pet' })
    await vi.advanceTimersByTimeAsync(600)
    expect(mocks.update).toHaveBeenCalledTimes(1)
    finish(response(mocks.update.mock.calls[0]![1], 1))
    await vi.advanceTimersByTimeAsync(0)
    expect(store.activeWorkspace.context.activeTab).toBe('pet')
    await vi.advanceTimersByTimeAsync(600)
    expect(mocks.update).toHaveBeenCalledTimes(2)
    expect(mocks.update.mock.calls[1]?.[1]).toMatchObject({ contextRevision: 1, context: { activeTab: 'pet' } })
    expect(store.contextSaveStatus.default).toBe('saved')
  })

  it('stops after two conflicts, keeps input, and supports explicit retry', async () => {
    mocks.update.mockRejectedValue(conflict(7))
    const store = useWorkspaceStore()
    store.updateWorkspaceContext('default', { activeTab: 'pet' })
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mocks.update).toHaveBeenCalledTimes(2)
    expect(store.contextSaveStatus.default).toBe('conflict')
    expect(store.activeWorkspace.context.activeTab).toBe('pet')
    mocks.update.mockImplementation(async (_id, patch) => response(patch, 8))
    store.retryContextSave('default')
    await vi.advanceTimersByTimeAsync(600)
    expect(store.contextSaveStatus.default).toBe('saved')
    expect(store.activeWorkspace.context.activeTab).toBe('pet')
  })

  it('persists original V3 JSON, selected alternate and edited rules through save and reload', async () => {
    mocks.update.mockImplementation(async (_id, patch) => response(patch, 1))
    const source = {
      spec: 'chara_card_v3', spec_version: '3.0', rootMetadata: { nested: ['root'] },
      data: {
        name: 'Imported', system_prompt: 'System', post_history_instructions: 'History',
        alternate_greetings: ['Alternate', ''], creator_notes: 'Author notes', tags: ['tag'],
        assets: [{ uri: 'embed://inert' }], extensions: { vendor: { nested: [1] } },
      },
    }
    const card = parseCharacterCard(source)
    card.name = 'Edited'
    card.greetingIndex = 1
    const store = useWorkspaceStore()
    store.updateWorkspaceContext('default', { roleCard: card })
    await vi.advanceTimersByTimeAsync(600)
    expect(store.contextSaveStatus.default).toBe('saved')
    disposePinia(pinia)
    pinia = createPinia()
    setActivePinia(pinia)
    const reloaded = useWorkspaceStore().activeWorkspace.context.roleCard
    expect(reloaded).toEqual(card)
    expect(getRoleCardGreeting(reloaded)).toBe('')
    const exported = exportCharacterCard(reloaded)
    expect(exported.spec).toBe('chara_card_v3')
    expect(exported.data).toMatchObject({
      name: 'Edited', system_prompt: 'System', post_history_instructions: 'History',
      creator_notes: 'Author notes', tags: ['tag'], assets: source.data.assets,
      extensions: { vendor: { nested: [1] }, yuizaki: { greetingIndex: 1 } },
    })
    const edited = cloneRoleCard(reloaded)
    edited.instructions = ''
    useWorkspaceStore().updateWorkspaceContext('default', { roleCard: edited })
    await vi.advanceTimersByTimeAsync(600)
    disposePinia(pinia)
    pinia = createPinia()
    setActivePinia(pinia)
    const cleared = useWorkspaceStore().activeWorkspace.context.roleCard
    expect(cleared.instructions).toBe('')
    expect(exportCharacterCard(cleared).data).toMatchObject({ system_prompt: '', post_history_instructions: '' })
    expect(parseCharacterCard(exportCharacterCard(cleared)).instructions).toBe('')
    expect(source.data.system_prompt).toBe('System')
  })

  it('normalizes server responses into independent greeting arrays and nested JSON', async () => {
    const card = parseCharacterCard({ name: 'Imported', alternate_greetings: ['Alt'], extensions: { vendor: { nested: [1] } } })
    card.greetingIndex = 0
    mocks.update.mockResolvedValue({ id: 'default', name: 'Local', created_at: null, updated_at: null, context: { roleCard: card }, contextRevision: 1 })
    const store = useWorkspaceStore()
    store.updateWorkspaceContext('default', { roleCard: card })
    await vi.advanceTimersByTimeAsync(600)
    const normalized = store.activeWorkspace.context.roleCard
    expect(normalized.alternateGreetings).not.toBe(card.alternateGreetings)
    expect(normalized.sourceCard).not.toBe(card.sourceCard)
    card.alternateGreetings!.push('Mutation')
    const extensions = card.sourceCard!.extensions as { vendor: { nested: number[] } }
    extensions.vendor.nested.push(2)
    expect(normalized.alternateGreetings).toEqual(['Alt'])
    expect(normalized.sourceCard!.extensions).toEqual({ vendor: { nested: [1] } })
    store.updateWorkspaceContext('default', { roleCard: createEmptyRoleCard() })
    expect(store.activeWorkspace.context.roleCard.sourceCard).toBeUndefined()
  })

  it.each([-2, 1, 0.5, '0', null])('resets invalid persisted greeting index %s and keeps old cards compatible', index => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([{
      id: 'default', name: 'Local', context: { roleCard: { enabled: false, name: 'Old', alternateGreetings: ['Alt'], greetingIndex: index, sourceCard: [] } },
    }]))
    const card = useWorkspaceStore().activeWorkspace.context.roleCard
    expect(card).toEqual({ ...createEmptyRoleCard(false), name: 'Old', alternateGreetings: ['Alt'], greetingIndex: -1 })
  })

  it('loads legacy cards with independent optional defaults and sanitizes persisted optional fields', () => {
    window.localStorage.setItem('deskpet-workspaces', JSON.stringify([{
      id: 'default', name: 'Local', context: { roleCard: { enabled: false, name: 'Old', description: 4, exampleDialogue: null, alternateGreetings: [1, 'Alt', null], greetingIndex: 9 } },
    }]))
    const card = useWorkspaceStore().activeWorkspace.context.roleCard
    expect(card).toEqual({ ...createEmptyRoleCard(false), name: 'Old', alternateGreetings: ['Alt'] })
  })

})

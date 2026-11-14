import { describe, expect, it } from 'vitest'
import type { WorkspaceRoleCard, WorkspaceWorldBook } from '../../../shared/workspace'
import { cloneRoleCard, createEmptyRoleCard, exportCharacterCard, getRoleCardGreeting, hasRoleCardContent, parseCharacterCard } from './character-card'

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const record = (value: unknown): Record<string, unknown> => value as Record<string, unknown>
const dataOf = (value: ReturnType<typeof exportCharacterCard>) => record(value.data ?? value)
const localCard: WorkspaceRoleCard = {
  ...createEmptyRoleCard(false), name: 'Yuizaki', description: '  Story.\nSecond line.  ',
  personality: 'Curious', scenario: 'Home', firstMessage: 'Hello, {{user}}!',
  exampleDialogue: '<START>\n{{char}}: Hello!\n', instructions: 'Local rules',
}
const core = {
  name: localCard.name, description: localCard.description, personality: localCard.personality,
  scenario: localCard.scenario, first_mes: localCard.firstMessage, mes_example: localCard.exampleDialogue,
  system_prompt: 'System text', post_history_instructions: 'Post-history text',
}
const metadata = {
  creator_notes: 'Author notes are not rules', tags: ['tag', '标签'], creator: 'Author', character_version: '1.2',
  version: { vendor: 7 }, assets: [{ uri: 'embed://image', ext: { opaque: true } }],
  extensions: { vendor: { unknown: ['preserve', { nested: null }] }, yuizaki: { custom: 'kept' } },
  alternate_greetings: ['Alternate', ''], extra: { macro: '{{inert}}', script: '<script>throw new Error("inert")</script>' },
}
const worldBook: WorkspaceWorldBook = {
  enabled: false, scanDepth: 6, budgetTokens: 1500, maxEntries: 5,
  entries: [{ id: 'entry_local', title: 'Home', keys: ['home'], secondaryKeys: ['room'], content: 'A quiet room',
    enabled: false, insertionOrder: 3, priority: 9, constant: true, selective: true,
    caseSensitive: true, matchWholeWords: true, probability: 70 }],
}
const serializedBook = () => record(dataOf(exportCharacterCard(localCard, worldBook)).character_book)

describe('local role card helpers', () => {
  it('creates independent defaults and explicitly clears stale source during assignment', () => {
    const first = createEmptyRoleCard(false)
    const second = createEmptyRoleCard()
    expect(first).toEqual({ enabled: false, name: '', description: '', personality: '', scenario: '', instructions: '',
      firstMessage: '', exampleDialogue: '', alternateGreetings: [], greetingIndex: -1, sourceCard: undefined })
    first.alternateGreetings!.push('Changed')
    expect(second.alternateGreetings).toEqual([])
    const target = parseCharacterCard(core)
    Object.assign(target, second)
    expect(target.sourceCard).toBeUndefined()
  })
  it('clones nested source and greeting arrays independently and clears absent source', () => {
    const source = parseCharacterCard({ ...core, ...copy(metadata) })
    source.greetingIndex = 1
    const clone = cloneRoleCard(source)
    expect(clone).toEqual(source)
    clone.alternateGreetings!.push('Changed')
    record(clone.sourceCard!.extra).macro = 'Changed'
    expect(source.alternateGreetings).toEqual(['Alternate', ''])
    expect(record(source.sourceCard!.extra).macro).toBe('{{inert}}')
    Object.assign(clone, cloneRoleCard(localCard))
    expect(clone.sourceCard).toBeUndefined()
  })
  it('fills optional old fields and resets invalid index', () => {
    const old = { enabled: false, name: 'Old', personality: '', scenario: '', instructions: '', firstMessage: '' }
    expect(cloneRoleCard(old)).toEqual({ ...createEmptyRoleCard(false), name: 'Old' })
    expect(cloneRoleCard({ ...localCard, alternateGreetings: ['a'], greetingIndex: 1 }).greetingIndex).toBe(-1)
  })
  it.each([-2, -1, 2, 1.5, NaN, Infinity, '0', null, undefined])('falls back to primary on invalid index %s', index => {
    expect(getRoleCardGreeting({ ...localCard, alternateGreetings: ['Alt', ''], greetingIndex: index as number })).toBe(localCard.firstMessage)
  })
  it('uses selected references verbatim, including empty strings', () => {
    const card = { ...localCard, alternateGreetings: ['  {{user}}\n', ''], greetingIndex: 0 }
    expect(getRoleCardGreeting(card)).toBe('  {{user}}\n')
    expect(getRoleCardGreeting({ ...card, greetingIndex: 1 })).toBe('')
    expect(getRoleCardGreeting({ ...card, alternateGreetings: undefined })).toBe(localCard.firstMessage)
  })
  it('allows alternate-only and imported metadata-only cards to be exported', () => {
    expect(hasRoleCardContent(createEmptyRoleCard())).toBe(false)
    expect(hasRoleCardContent({ ...createEmptyRoleCard(), alternateGreetings: ['Reference'] })).toBe(true)
    const imported = parseCharacterCard({ name: '', ...copy(metadata) })
    imported.alternateGreetings = []
    expect(hasRoleCardContent(imported)).toBe(true)
    expect(dataOf(exportCharacterCard(imported)).creator_notes).toBe(metadata.creator_notes)
  })
})

describe('character card parsing and export', () => {
  it('keeps distinct text fields verbatim and stores independent inert JSON', () => {
    const source = { ...core, ...copy(metadata) }
    const card = parseCharacterCard(source)
    expect(card).toEqual({ ...localCard, enabled: true, instructions: 'System text\n\nPost-history text', alternateGreetings: ['Alternate', ''], sourceCard: source })
    source.extensions.vendor.unknown.push('mutation')
    expect(card.sourceCard).not.toEqual(source)
  })
  it.each(['v1', 'wrapped-v1', 'chara_card_v2', 'chara_card_v3'])('changes only name in %s, preserving metadata and rule split', spec => {
    const data = { ...core, ...copy(metadata) }
    const source = spec === 'v1' ? data : spec === 'wrapped-v1' ? { opaque: [1], data }
      : { spec, spec_version: spec === 'chara_card_v2' ? '2.0' : '3.0', name: 'Root name', opaque: { a: true }, data }
    const before = copy(source)
    const card = parseCharacterCard(JSON.stringify(source))
    expect(exportCharacterCard(card)).toEqual(source)
    card.name = 'Renamed'
    const expected = copy(source)
    record(record(expected).data ?? expected).name = 'Renamed'
    const exported = exportCharacterCard(card)
    expect(exported).toEqual(expected)
    expect(dataOf(exported).system_prompt).toBe(core.system_prompt)
    expect(dataOf(exported).post_history_instructions).toBe(core.post_history_instructions)
    record(record(dataOf(exported).extensions).vendor).unknown = []
    expect(card.sourceCard).toEqual(before)
    expect(source).toEqual(before)
  })
  it.each([['character_name', 'first_message', 'example_dialogue'], ['characterName', 'firstMes', 'mesExample'], ['name', 'firstMessage', 'exampleDialogue']])('keeps alias placement %s / %s / %s', (name, first, example) => {
    const source = { [name]: 'Alias', [first]: 'Hi', [example]: 'Example', instructions: 'Local', systemPrompt: 'System', postHistoryInstructions: 'History' }
    const card = parseCharacterCard(source)
    expect(card).toMatchObject({ name: 'Alias', firstMessage: 'Hi', exampleDialogue: 'Example', instructions: 'Local\n\nSystem\n\nHistory' })
    card.name = ''
    expect(exportCharacterCard(card)).toEqual({ ...source, [name]: '' })
  })
  it.each(['New rules', ''])('replaces the aggregate with %j without reintroducing any old rules', instructions => {
    const source = { spec: 'chara_card_v3', spec_version: '3.0', data: { ...core, ...copy(metadata),
      instructions: 'Legacy', systemPrompt: 'System alias', postHistoryInstructions: 'History alias',
      extensions: { ...copy(metadata.extensions), yuizaki: { instructions: 'Old fallback', custom: 'kept' } } } }
    let card = parseCharacterCard(source)
    card.instructions = instructions
    const exported = exportCharacterCard(card)
    expect(dataOf(exported)).toMatchObject({ system_prompt: instructions, post_history_instructions: '', instructions: '', systemPrompt: '', postHistoryInstructions: '' })
    expect(record(record(dataOf(exported).extensions).yuizaki)).toEqual({ instructions, custom: 'kept' })
    expect(dataOf(exported).creator_notes).toBe(metadata.creator_notes)
    for (let i = 0; i < 3; i += 1) {
      card = parseCharacterCard(copy(exportCharacterCard(card)))
      expect(card.instructions).toBe(instructions)
    }
  })
  it('writes explicit empty edits and preserves canonical empty values over aliases', () => {
    const card = parseCharacterCard({ ...core, ...copy(metadata) })
    Object.assign(card, { name: '', description: '', personality: '', scenario: '', firstMessage: '', exampleDialogue: '', alternateGreetings: [] })
    expect(dataOf(exportCharacterCard(card))).toMatchObject({ name: '', description: '', personality: '', scenario: '', first_mes: '', mes_example: '', alternate_greetings: [], system_prompt: core.system_prompt, post_history_instructions: core.post_history_instructions })
    expect(parseCharacterCard({ name: '', character_name: 'Alias', first_mes: '', firstMessage: 'Alias' })).toMatchObject({ name: '', firstMessage: '' })
  })
  it.each(['instructions', 'system_prompt', 'systemPrompt', 'post_history_instructions', 'postHistoryInstructions'])('uses explicit empty %s over extension fallback', key => {
    expect(parseCharacterCard({ [key]: '', extensions: { yuizaki: { instructions: 'OLD' } } }).instructions).toBe('')
  })
  it('uses extension rules only when core rules are absent and preserves enabled precedence', () => {
    const source = { name: 'Fallback', enabled: true, extensions: { yuizaki: { instructions: '  OLD\n', enabled: false } } }
    expect(parseCharacterCard(source)).toMatchObject({ instructions: '  OLD\n', enabled: false })
    expect(exportCharacterCard(parseCharacterCard(source))).toEqual(source)
    expect(parseCharacterCard({ name: 'No state' }, false).enabled).toBe(false)
  })
  it('creates a full V2 card and round-trips new cards without duplication', () => {
    const exported = exportCharacterCard(localCard)
    expect(exported).toEqual({ spec: 'chara_card_v2', spec_version: '2.0', data: {
      ...core, system_prompt: localCard.instructions, post_history_instructions: '', creator_notes: '', alternate_greetings: [], tags: [], creator: '', character_version: '',
      extensions: { yuizaki: { enabled: false, instructions: localCard.instructions } } } })
    expect(dataOf(exported)).not.toHaveProperty('sourceCard')
    let card = localCard
    for (let i = 0; i < 3; i += 1) {
      card = parseCharacterCard(copy(exportCharacterCard(card)))
      expect({ ...card, sourceCard: undefined }).toEqual(localCard)
    }
  })
  it('round-trips selected greetings and keeps unknown extensions', () => {
    const card = parseCharacterCard({ data: { ...core, ...copy(metadata) } })
    card.alternateGreetings = ['Changed', '']
    card.greetingIndex = 1
    const exported = exportCharacterCard(card)
    expect(dataOf(exported).extensions).toEqual({ ...metadata.extensions, yuizaki: { custom: 'kept', greetingIndex: 1 } })
    const reloaded = parseCharacterCard(copy(exported))
    expect(reloaded.alternateGreetings).toEqual(['Changed', ''])
    expect(reloaded.greetingIndex).toBe(1)
    expect(getRoleCardGreeting(reloaded)).toBe('')
    reloaded.greetingIndex = -1
    expect(parseCharacterCard(exportCharacterCard(reloaded)).greetingIndex).toBe(-1)
  })
  it.each([null, undefined, true, 4, [], {}, { enabled: false }, { unknown: 'text' }, { data: {} }, { data: [] }, { data: null }, { data: 'wrong', name: 'No fallback' }, { spec: 'chara_card_v2', name: 'Missing data' }, { spec: 'unknown', data: { name: 'Wrong spec' } }])('rejects invalid shape %#', source => {
    expect(() => parseCharacterCard(source)).toThrow(TypeError)
  })
  it.each(Object.keys(core).concat(['instructions', 'character_name', 'characterName', 'firstMessage', 'first_message', 'firstMes', 'exampleDialogue', 'example_dialogue', 'mesExample', 'systemPrompt', 'postHistoryInstructions']))('rejects non-string %s', field => {
    for (const value of [null, undefined, false, 42, [], {}]) {
      expect(() => parseCharacterCard({ ...core, [field]: value })).toThrow(TypeError)
      expect(() => parseCharacterCard({ data: { ...core, [field]: value } })).toThrow(TypeError)
    }
  })
  it.each([null, undefined, false, 42, 'text', {}, ['valid', 1], ['valid', null]])('strictly rejects invalid alternate_greetings %#', value => {
    expect(() => parseCharacterCard({ ...core, alternate_greetings: value })).toThrow(TypeError)
    expect(() => parseCharacterCard({ data: { ...core, alternate_greetings: value } })).toThrow(TypeError)
  })
  it('rejects malformed JSON', () => { expect(() => parseCharacterCard('{broken')).toThrow(SyntaxError) })
})

describe('character book preservation', () => {
  it('independently exports new entries and explicitly deletes all entries', () => {
    const before = copy(worldBook)
    const exported = exportCharacterCard(localCard, worldBook)
    const book = record(dataOf(exported).character_book)
    expect(book).toMatchObject({ scan_depth: 6, token_budget: 1500, extensions: { yuizaki: { enabled: false, maxEntries: 5 } } })
    const entries = book.entries as Record<string, unknown>[]
    const keys = entries[0]!.keys as string[]
    keys.push('changed')
    expect(worldBook).toEqual(before)
    expect(dataOf(exportCharacterCard(localCard))).not.toHaveProperty('character_book')
    const card = parseCharacterCard(exported)
    expect(record(dataOf(exportCharacterCard(card, { ...worldBook, entries: [] })).character_book).entries).toEqual([])
  })
  it('preserves unedited metadata, settings and entry extensions when renaming a character', () => {
    const book = serializedBook()
    const entry = (book.entries as Record<string, unknown>[])[0]!
    Object.assign(book, { name: 'Lore', recursive_scanning: true, metadata: { arbitrary: [1, { k: 'v' }] } })
    record(book.extensions).vendor = { arbitrary: true }
    record(record(book.extensions).yuizaki).extra = 'keep'
    Object.assign(entry, { id: 7, position: 'after_char', comment: 'Untouched', unknown: { script: '{{inert}}' } })
    record(entry.extensions).vendor = { depth: 19 }
    const card = parseCharacterCard({ ...core, character_book: book })
    card.name = 'Renamed'
    const supplied = { ...worldBook, entries: [{ ...worldBook.entries[0]!, id: '7', title: 'Untouched' }] }
    expect(dataOf(exportCharacterCard(card, supplied)).character_book).toEqual(book)
    expect(dataOf(exportCharacterCard(card)).character_book).toEqual(book)
  })
  it('matches stable ids through deletion and edits and adds entries without borrowing deleted metadata', () => {
    const book = serializedBook()
    const first = (book.entries as Record<string, unknown>[])[0]!
    first.unknown = 'first'
    first.id = ''
    record(first.extensions).vendor = { keep: true }
    const second = copy(first)
    record(record(second.extensions).yuizaki).id = 'second'
    second.insertion_order = 9
    second.unknown = 'second'
    book.entries = [first, second]
    const card = parseCharacterCard({ ...core, character_book: book })
    const updated = { ...worldBook, entries: [{ ...worldBook.entries[0]!, id: 'second', insertionOrder: 9, content: 'Edited' }, { ...worldBook.entries[0]!, id: 'new', insertionOrder: 10 }] }
    const entries = record(dataOf(exportCharacterCard(card, updated)).character_book).entries as Record<string, unknown>[]
    expect(entries).toHaveLength(2)
    expect(entries[0]).toMatchObject({ unknown: 'second', content: 'Edited', extensions: { vendor: { keep: true } } })
    expect(entries[1]).not.toHaveProperty('unknown')
    expect(entries[1]).toMatchObject({ extensions: { yuizaki: { id: 'new' } } })
    expect((book.entries as Record<string, unknown>[])[1]!.content).toBe('A quiet room')
  })
  it('matches id-less insertion order and preserves dictionary entry structure', () => {
    const book = serializedBook()
    const first = (book.entries as Record<string, unknown>[])[0]!
    delete record(record(first.extensions).yuizaki).id
    first.opaque = { retained: true }
    const card = parseCharacterCard({ data: { ...core, character_book: book } })
    const changed = { ...worldBook, entries: [{ ...worldBook.entries[0]!, id: 'ui-generated', content: 'Edited' }] }
    expect(record(dataOf(exportCharacterCard(card, changed)).character_book).entries).toEqual([{ ...first, content: 'Edited' }])
    book.entries = { entry_local: first }
    const dictionaryCard = parseCharacterCard({ ...core, character_book: book })
    expect(record(dataOf(exportCharacterCard(dictionaryCard, worldBook)).character_book).entries).toEqual({ entry_local: first })
  })
  it('writes changed book settings and entry flags without stale aliases overriding the edits', () => {
    const book = serializedBook()
    const entry = (book.entries as Record<string, unknown>[])[0]!
    delete entry.enabled
    entry.disable = true
    entry.disabled = true
    delete entry.case_sensitive
    record(entry.extensions).case_sensitive = true
    record(entry.extensions).match_whole_words = true
    entry.probability = 12
    entry.use_probability = false
    entry.opaque = { keep: ['value'] }
    Object.assign(book, { scanDepth: 6, max_entries: 5, enabled: false, token_budget: 1500 })
    record(book.extensions).opaque = { keep: true }
    const card = parseCharacterCard({ ...core, character_book: book })
    const updated: WorkspaceWorldBook = { ...worldBook, enabled: true, scanDepth: 9, maxEntries: 11, budgetTokens: 1800,
      entries: [{ ...worldBook.entries[0]!, enabled: true, caseSensitive: false, matchWholeWords: false, probability: 30 }] }
    const result = record(dataOf(exportCharacterCard(card, updated)).character_book)
    expect(result).toMatchObject({ scan_depth: 9, scanDepth: 9, max_entries: 11, enabled: true, token_budget: 1800,
      extensions: { opaque: { keep: true }, yuizaki: { enabled: true, maxEntries: 11 } } })
    expect((result.entries as unknown[])[0]).toMatchObject({ enabled: true, disable: false, disabled: false,
      case_sensitive: false, probability: 30, use_probability: true, opaque: { keep: ['value'] },
      extensions: { case_sensitive: false, match_whole_words: false, yuizaki: { matchWholeWords: false, probability: 30 } } })
    expect(book).toMatchObject({ enabled: false, max_entries: 5, scanDepth: 6 })
  })

})

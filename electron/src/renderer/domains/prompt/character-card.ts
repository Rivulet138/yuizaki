import type { WorkspaceRoleCard, WorkspaceWorldBook } from '../../../shared/workspace'

const fields = {
  name: ['name', 'character_name', 'characterName'],
  description: ['description'],
  personality: ['personality'],
  scenario: ['scenario'],
  firstMessage: ['first_mes', 'firstMessage', 'first_message', 'firstMes'],
  exampleDialogue: ['mes_example', 'exampleDialogue', 'example_dialogue', 'mesExample'],
  instructions: ['instructions'],
  systemPrompt: ['system_prompt', 'systemPrompt'],
  postHistoryInstructions: ['post_history_instructions', 'postHistoryInstructions'],
} as const

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// JSON copying also works with Vue proxies. Imported metadata stays inert JSON.
const copyJson = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

const readString = (source: Record<string, unknown>, keys: readonly string[]): string => {
  for (const key of keys) {
    if (typeof source[key] === 'string') return source[key]
  }
  return ''
}

export const createEmptyRoleCard = (enabled = true): WorkspaceRoleCard => ({
  enabled,
  name: '',
  description: '',
  personality: '',
  scenario: '',
  instructions: '',
  firstMessage: '',
  exampleDialogue: '',
  alternateGreetings: [],
  greetingIndex: -1,
  sourceCard: undefined,
})

/** Select a reference only; callers must not insert it into message history. */
export const getRoleCardGreeting = (card: WorkspaceRoleCard): string => {
  const index = card.greetingIndex ?? -1
  const greetings = card.alternateGreetings ?? []
  return Number.isInteger(index) && index >= 0 && index < greetings.length
    ? greetings[index]! : card.firstMessage
}

/** Return an independent local card, filling optional fields from older workspaces. */
export const cloneRoleCard = (source: WorkspaceRoleCard): WorkspaceRoleCard => {
  const alternateGreetings = [...(source.alternateGreetings ?? [])]
  const index = source.greetingIndex ?? -1
  return {
    enabled: source.enabled !== false,
    name: source.name,
    description: source.description ?? '',
    personality: source.personality,
    scenario: source.scenario,
    instructions: source.instructions,
    firstMessage: source.firstMessage,
    exampleDialogue: source.exampleDialogue ?? '',
    alternateGreetings,
    greetingIndex: Number.isInteger(index) && index >= -1 && index < alternateGreetings.length ? index : -1,
    sourceCard: source.sourceCard ? copyJson(source.sourceCard) : undefined,
  }
}

export const hasRoleCardContent = (roleCard: WorkspaceRoleCard): boolean =>
  Boolean(roleCard.sourceCard) || [roleCard.name, roleCard.description, roleCard.personality, roleCard.scenario,
    roleCard.instructions, roleCard.firstMessage, roleCard.exampleDialogue, ...(roleCard.alternateGreetings ?? [])]
    .some(value => Boolean(value?.trim()))

/** Import text fields and preserve the original JSON without evaluating any of it. */
export const parseCharacterCard = (source: unknown, currentEnabled = true): WorkspaceRoleCard => {
  const root: unknown = typeof source === 'string' ? JSON.parse(source) : source
  if (!isRecord(root)) throw new TypeError('Character card must be a JSON object')
  if (Object.hasOwn(root, 'spec') && root.spec !== 'chara_card_v2' && root.spec !== 'chara_card_v3') {
    throw new TypeError('Unsupported character card spec')
  }
  const wrapped = Object.hasOwn(root, 'data')
  if ((Object.hasOwn(root, 'spec') || wrapped) && !isRecord(root.data)) {
    throw new TypeError('Character card data must be an object')
  }
  const data = wrapped ? root.data as Record<string, unknown> : root
  let hasCoreField = false
  for (const aliases of Object.values(fields)) {
    for (const key of aliases) {
      if (!Object.hasOwn(data, key)) continue
      if (typeof data[key] !== 'string') throw new TypeError(`Character card field ${key} must be a string`)
      hasCoreField = true
    }
  }
  if (!hasCoreField) throw new TypeError('Character card has no supported role fields')
  const alternateGreetings = data.alternate_greetings ?? data.alternateGreetings ?? []
  for (const key of ['alternate_greetings', 'alternateGreetings']) {
    if (Object.hasOwn(data, key) && (!Array.isArray(data[key]) || !(data[key] as unknown[]).every(value => typeof value === 'string'))) {
      throw new TypeError(`Character card field ${key} must be an array of strings`)
    }
  }
  const extensions = isRecord(data.extensions) ? data.extensions : undefined
  const local = isRecord(extensions?.yuizaki) ? extensions.yuizaki : undefined
  const instructionFields = [fields.instructions, fields.systemPrompt, fields.postHistoryInstructions]
  const hasInstructionField = instructionFields.some(aliases => aliases.some(key => Object.hasOwn(data, key)))
  const instructionParts = instructionFields.map(aliases => readString(data, aliases))
    .filter(value => value !== '')
  // Explicit empty core instructions override the local fallback, too.
  const instructions = hasInstructionField
    ? instructionParts.join('\n\n')
    : typeof local?.instructions === 'string' ? local.instructions : ''
  const greetings = [...alternateGreetings as string[]]
  const index = local?.greetingIndex ?? data.greetingIndex ?? -1
  return {
    enabled: typeof local?.enabled === 'boolean' ? local.enabled
      : typeof data.enabled === 'boolean' ? data.enabled : currentEnabled,
    name: readString(data, fields.name),
    description: readString(data, fields.description),
    personality: readString(data, fields.personality),
    scenario: readString(data, fields.scenario),
    firstMessage: readString(data, fields.firstMessage),
    exampleDialogue: readString(data, fields.exampleDialogue),
    instructions,
    alternateGreetings: greetings,
    greetingIndex: typeof index === 'number' && Number.isInteger(index) && index >= -1 && index < greetings.length ? index : -1,
    sourceCard: copyJson(root),
  }
}

/** Update existing aliases in place; add the canonical field only when absent. */
const writeField = (target: Record<string, unknown>, keys: readonly string[], value: unknown) => {
  const present = keys.filter(key => Object.hasOwn(target, key))
  for (const key of present.length ? present : [keys[0]!]) target[key] = value
}

const writeLocal = (target: Record<string, unknown>, patch: Record<string, unknown>) => {
  const extensions = isRecord(target.extensions) ? target.extensions : {}
  const local = isRecord(extensions.yuizaki) ? extensions.yuizaki : {}
  target.extensions = { ...extensions, yuizaki: { ...local, ...patch } }
}

const exportWorldBook = (worldBook: WorkspaceWorldBook, original: unknown): Record<string, unknown> => {
  const book = isRecord(original) ? copyJson(original) : {}
  const rawEntries = book.entries
  const entries = Array.isArray(rawEntries) ? rawEntries.map((value, index) => [String(index), value] as const)
    : isRecord(rawEntries) ? Object.entries(rawEntries) : []
  const used = new Set<number>()
  const record = (value: unknown): Record<string, unknown> => isRecord(value) ? value : {}
  const number = (raw: Record<string, unknown>, aliases: string[], fallback: number): number => {
    for (const key of aliases) {
      if (raw[key] !== undefined && Number.isFinite(Number(raw[key]))) return Number(raw[key])
    }
    return fallback
  }
  const boolean = (raw: Record<string, unknown>, aliases: string[], fallback: boolean): boolean => {
    for (const key of aliases) if (typeof raw[key] === 'boolean') return raw[key] as boolean
    return fallback
  }
  const list = (raw: Record<string, unknown>, aliases: string[]): string[] => {
    for (const key of aliases) if (Array.isArray(raw[key])) return (raw[key] as unknown[]).filter((value): value is string => typeof value === 'string')
    return []
  }
  const identifier = (raw: Record<string, unknown>, key?: string) => {
    const local = record(record(raw.extensions).yuizaki)
    for (const value of [raw.id, raw.uid, local.id, key]) {
      if (typeof value === 'string' && value.trim()) return value.trim()
      if (typeof value === 'number' && Number.isFinite(value)) return String(value)
    }
    return ''
  }
  const exportedEntries = worldBook.entries.map(entry => {
    let match = entries.findIndex(([key, value], index) => !used.has(index)
      && identifier(record(value), isRecord(rawEntries) ? key : undefined) === entry.id)
    if (match < 0) {
      // Generated UI ids have no counterpart in a source entry without an id.
      match = entries.findIndex(([key, value], index) => !used.has(index) && !identifier(record(value), isRecord(rawEntries) ? key : undefined)
        && number(record(value), ['insertionOrder', 'insertion_order', 'order'], index) === entry.insertionOrder)
    }
    if (match >= 0) used.add(match)
    const raw = match >= 0 ? record(entries[match]![1]) : {}
    const result = copyJson(raw)
    const extensions = record(raw.extensions)
    const local = record(extensions.yuizaki)
    const secondaryKeys = list(raw, ['secondaryKeys', 'secondary_keys', 'keysecondary', 'secondary', 'secondaryKeywords', 'secondary_keywords'])
    const id = identifier(raw, isRecord(rawEntries) && match >= 0 ? entries[match]![0] : undefined)
    const values: [readonly string[], unknown, unknown][] = [
      [['name', 'title', 'comment', 'memo', 'displayName'], entry.title, readString(raw, ['title', 'comment', 'name', 'memo', 'displayName']) || id || entry.title],
      [['keys', 'key', 'primaryKeys', 'primary_keys', 'keywords', 'triggers'], entry.keys, list(raw, ['keys', 'key', 'primaryKeys', 'primary_keys', 'keywords', 'triggers'])],
      [['secondary_keys', 'secondaryKeys', 'keysecondary', 'secondary', 'secondaryKeywords', 'secondary_keywords'], entry.secondaryKeys, secondaryKeys],
      [['content', 'entry', 'text', 'value', 'prompt'], entry.content, readString(raw, ['content', 'entry', 'text', 'value', 'prompt']).trim()],
      [['enabled'], entry.enabled, raw.enabled === false ? false : !boolean(raw, ['disable', 'disabled'], false)],
      [['insertion_order', 'insertionOrder', 'order'], entry.insertionOrder, number(raw, ['insertionOrder', 'insertion_order', 'order'], match)],
      [['case_sensitive', 'caseSensitive'], entry.caseSensitive, boolean(raw, ['caseSensitive', 'case_sensitive'], false) || boolean(extensions, ['case_sensitive'], false)],
      [['priority'], entry.priority, number(raw, ['priority'], 0)],
      [['constant'], entry.constant, boolean(raw, ['constant'], false)],
      [['selective'], entry.selective, boolean(raw, ['selective'], secondaryKeys.length > 0)],
    ]
    for (const [aliases, value, previous] of values) {
      if (match < 0 || JSON.stringify(value) !== JSON.stringify(previous)) writeField(result, aliases, copyJson(value))
    }
    if (entry.enabled && boolean(raw, ['disable', 'disabled'], false)) {
      for (const key of ['disable', 'disabled']) if (Object.hasOwn(result, key)) result[key] = false
    }
    if (entry.caseSensitive !== (boolean(raw, ['caseSensitive', 'case_sensitive'], false) || boolean(extensions, ['case_sensitive'], false))
      && Object.hasOwn(extensions, 'case_sensitive')) {
      record(result.extensions).case_sensitive = entry.caseSensitive
    }
    if (match < 0) writeLocal(result, { id: entry.id, matchWholeWords: entry.matchWholeWords, probability: entry.probability })
    else {
      const wholeWords = boolean(raw, ['matchWholeWords', 'match_whole_words'], false)
        || boolean(extensions, ['match_whole_words'], false) || boolean(local, ['matchWholeWords'], false)
      const probability = boolean(raw, ['useProbability', 'use_probability'], true)
        ? Math.max(0, Math.min(100, number(raw, ['probability'], number(local, ['probability'], 100)))) : 100
      if (entry.matchWholeWords !== wholeWords) {
        writeLocal(result, { matchWholeWords: entry.matchWholeWords })
        for (const key of ['matchWholeWords', 'match_whole_words']) if (Object.hasOwn(result, key)) result[key] = entry.matchWholeWords
        if (Object.hasOwn(extensions, 'match_whole_words')) record(result.extensions).match_whole_words = entry.matchWholeWords
      }
      if (entry.probability !== probability) {
        writeLocal(result, { probability: entry.probability })
        if (Object.hasOwn(result, 'probability')) result.probability = entry.probability
        for (const key of ['useProbability', 'use_probability']) if (Object.hasOwn(result, key)) result[key] = true
      }
    }
    // Keep the original dictionary key when the source uses an entries object.
    return [match >= 0 ? entries[match]![0] : entry.id, result] as const
  })
  const local = record(record(book.extensions).yuizaki)
  if (!isRecord(original) || worldBook.scanDepth !== number(book, ['scanDepth', 'scan_depth', 'depth'], 8)) {
    writeField(book, ['scan_depth', 'scanDepth', 'depth'], worldBook.scanDepth)
  }
  if (!isRecord(original) || worldBook.budgetTokens !== number(book, ['budgetTokens', 'budget_tokens', 'token_budget'], 1200)) {
    writeField(book, ['token_budget', 'budgetTokens', 'budget_tokens'], worldBook.budgetTokens)
  }
  if (!isRecord(original) || worldBook.enabled !== boolean(book, ['enabled'], boolean(local, ['enabled'], true))) {
    writeLocal(book, { enabled: worldBook.enabled })
    if (Object.hasOwn(book, 'enabled')) book.enabled = worldBook.enabled
  }
  if (!isRecord(original) || worldBook.maxEntries !== number(book, ['maxEntries', 'max_entries'], number(local, ['maxEntries'], Math.max(8, entries.length)))) {
    writeLocal(book, { maxEntries: worldBook.maxEntries })
    for (const key of ['maxEntries', 'max_entries']) if (Object.hasOwn(book, key)) book[key] = worldBook.maxEntries
  }
  if (rawEntries !== undefined || exportedEntries.length || !isRecord(original)) {
    book.entries = isRecord(rawEntries) ? Object.fromEntries(exportedEntries) : exportedEntries.map(([, entry]) => entry)
  }
  return book
}

/** V1 is a root object; V2/V3 retain their imported wrapper and version. */
export interface CharacterCardJson extends Record<string, unknown> {
  data?: Record<string, unknown>
}

export const exportCharacterCard = (roleCard: WorkspaceRoleCard, worldBook?: WorkspaceWorldBook): CharacterCardJson => {
  const card = cloneRoleCard(roleCard)
  const root: CharacterCardJson = card.sourceCard ? copyJson(card.sourceCard) : {
    spec: 'chara_card_v2', spec_version: '2.0',
    data: {
      name: card.name, description: card.description, personality: card.personality, scenario: card.scenario,
      first_mes: card.firstMessage, mes_example: card.exampleDialogue,
      system_prompt: card.instructions, post_history_instructions: '', creator_notes: '',
      alternate_greetings: [...card.alternateGreetings!], tags: [], creator: '', character_version: '',
      extensions: { yuizaki: { enabled: card.enabled, instructions: card.instructions } },
    },
  }
  const data = isRecord(root.data) ? root.data : root
  if (card.sourceCard) {
    const previous = parseCharacterCard(card.sourceCard, card.enabled)
    for (const key of ['name', 'description', 'personality', 'scenario', 'firstMessage', 'exampleDialogue'] as const) {
      if (card[key] !== previous[key]) writeField(data, fields[key], card[key])
    }
    if (card.instructions !== previous.instructions) {
      // An edited aggregate replaces every old rule source, including aliases.
      for (const key of [...fields.instructions, ...fields.systemPrompt, ...fields.postHistoryInstructions]) {
        if (Object.hasOwn(data, key)) data[key] = ''
      }
      data.system_prompt = card.instructions
      data.post_history_instructions = ''
      const local = isRecord(data.extensions) && isRecord(data.extensions.yuizaki) ? data.extensions.yuizaki : undefined
      if (local && Object.hasOwn(local, 'instructions')) local.instructions = card.instructions
    }
    if (card.enabled !== previous.enabled) {
      writeLocal(data, { enabled: card.enabled })
      if (Object.hasOwn(data, 'enabled')) data.enabled = card.enabled
    }
    if (JSON.stringify(card.alternateGreetings) !== JSON.stringify(previous.alternateGreetings)) {
      writeField(data, ['alternate_greetings', 'alternateGreetings'], [...card.alternateGreetings!])
    }
    if (card.greetingIndex !== previous.greetingIndex) {
      writeLocal(data, { greetingIndex: card.greetingIndex })
      if (Object.hasOwn(data, 'greetingIndex')) data.greetingIndex = card.greetingIndex
    }
  } else if (card.greetingIndex !== -1) writeLocal(data, { greetingIndex: card.greetingIndex })
  if (worldBook) data.character_book = exportWorldBook(worldBook, data.character_book)
  return root
}

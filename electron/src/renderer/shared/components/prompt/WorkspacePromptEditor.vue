<template>
  <div class="workspace-prompt-editor" :class="{ 'is-dense': dense }">
    <section v-if="showMode" class="prompt-section">
      <header class="prompt-section-header">
        <h3>提示词模式</h3>
      </header>
      <div class="mode-segment">
        <button
          v-for="mode in promptModeOptions"
          :key="mode.value"
          type="button"
          :class="{ active: workspacePromptMode === mode.value }"
          @click="workspacePromptMode = mode.value"
        >
          {{ mode.label }}
        </button>
      </div>
    </section>

    <section class="prompt-section">
      <header class="prompt-section-header">
        <h3>基础提示词</h3>
        <el-button size="small" text @click="resetBasePrompts">恢复默认</el-button>
      </header>
      <el-form class="prompt-form" label-position="top" @submit.prevent>
        <el-form-item label="任务模式">
          <el-input v-model="promptEngineeringModel.workPrompt" type="textarea" :rows="dense ? 4 : 6" resize="none" />
        </el-form-item>
        <el-form-item label="日常陪伴">
          <el-input v-model="promptEngineeringModel.dailyPrompt" type="textarea" :rows="dense ? 4 : 6" resize="none" />
        </el-form-item>
      </el-form>
    </section>

    <section class="prompt-section">
      <header class="prompt-section-header">
        <h3>人格角色卡</h3>
        <div class="section-actions">
          <input ref="roleCardFileInput" class="hidden-file-input" type="file" accept=".json,application/json" @change="importRoleCardFile">
          <el-button size="small" plain @click="openRoleCardFilePicker">导入</el-button>
          <el-button size="small" plain :disabled="!hasRoleCardContent(roleCardModel) || Boolean(roleCardJsonError)" @click="exportRoleCardFile">导出</el-button>
          <el-switch v-model="roleCardModel.enabled" size="small" inline-prompt active-text="开" inactive-text="关" />
        </div>
      </header>

      <el-form class="prompt-form" label-position="top" @submit.prevent>
        <el-form-item label="角色卡 JSON">
          <el-input
            v-model="roleCardJson"
            type="textarea"
            :rows="dense ? 8 : 12"
            resize="none"
            placeholder="{&#10;  &quot;name&quot;: &quot;結崎&quot;,&#10;  &quot;personality&quot;: &quot;温暖、轻快&quot;,&#10;  &quot;scenario&quot;: &quot;住在桌面上的本地 AI 桌宠&quot;,&#10;  &quot;instructions&quot;: &quot;回答简短自然&quot;,&#10;  &quot;firstMessage&quot;: &quot;今天也在这里。&quot;&#10;}"
          />
        </el-form-item>
        <p v-if="roleCardJsonError" class="prompt-field-error">{{ roleCardJsonError }}</p>
      </el-form>
    </section>

    <section class="prompt-section">
      <header class="prompt-section-header">
        <h3>世界书</h3>
        <el-switch v-model="worldBookModel.enabled" size="small" inline-prompt active-text="开" inactive-text="关" />
      </header>

      <div class="world-book-options">
        <label>
          <span>扫描深度</span>
          <el-input-number v-model="worldBookModel.scanDepth" size="small" :min="1" :max="32" controls-position="right" />
        </label>
        <label>
          <span>条目上限</span>
          <el-input-number v-model="worldBookModel.maxEntries" size="small" :min="1" :max="64" controls-position="right" />
        </label>
        <label>
          <span>预算</span>
          <el-input-number v-model="worldBookModel.budgetTokens" size="small" :min="128" :max="32000" :step="128" controls-position="right" />
        </label>
      </div>

      <div class="world-toolbar">
        <el-input v-model="worldBookSearch" size="small" placeholder="筛选条目" clearable />
        <div class="mode-segment world-state-filter">
          <button
            v-for="option in worldBookStateFilterOptions"
            :key="option.value"
            type="button"
            :class="{ active: worldBookStateFilter === option.value }"
            @click="worldBookStateFilter = option.value"
          >
            {{ option.label }}
          </button>
        </div>
        <span class="world-entry-count">{{ worldEntryRangeLabel }}</span>
      </div>

      <div v-if="worldBookModel.entries.length" class="world-batch-bar">
        <el-checkbox
          :model-value="allFilteredWorldEntriesSelected"
          :indeterminate="isWorldEntrySelectionPartial"
          :disabled="filteredWorldEntries.length === 0"
          @change="toggleFilteredWorldEntrySelection"
        >
          选中结果
        </el-checkbox>
        <span>{{ selectedWorldEntryIds.length }} 已选</span>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="batchSetWorldEntriesEnabled(true)">启用</el-button>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="batchSetWorldEntriesEnabled(false)">停用</el-button>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="exportSelectedWorldBookFile">导出选中</el-button>
        <el-button size="small" text type="danger" :disabled="selectedWorldEntryIds.length === 0" @click="removeSelectedWorldEntries">删除选中</el-button>
      </div>

      <div class="world-import-row">
        <el-input
          v-model="worldBookJson"
          type="textarea"
          :rows="dense ? 3 : 4"
          resize="none"
          placeholder="粘贴 character_book、entries 或世界书 JSON"
        />
        <div class="world-import-actions">
          <div class="mode-segment world-import-mode">
            <button
              type="button"
              :class="{ active: worldBookImportMode === 'replace' }"
              @click="worldBookImportMode = 'replace'"
            >
              替换
            </button>
            <button
              type="button"
              :class="{ active: worldBookImportMode === 'merge' }"
              @click="worldBookImportMode = 'merge'"
            >
              追加
            </button>
          </div>
          <input ref="worldBookFileInput" class="hidden-file-input" type="file" accept=".json,application/json" @change="importWorldBookFile">
          <el-button size="small" plain @click="openWorldBookFilePicker">导入文件</el-button>
          <el-button size="small" type="primary" plain :disabled="!worldBookJson.trim()" @click="importWorldBookJson">导入 JSON</el-button>
          <el-button size="small" plain :disabled="!worldBookModel.entries.length" @click="exportWorldBookFile">导出文件</el-button>
          <el-button size="small" text :disabled="!worldBookJson.trim()" @click="worldBookJson = ''">清空</el-button>
        </div>
      </div>
      <p v-if="worldBookJsonError" class="prompt-field-error">{{ worldBookJsonError }}</p>

      <div v-if="worldBookModel.entries.length" class="world-preview" data-testid="world-book-preview">
        <div class="world-preview-head">
          <span>触发预览</span>
          <span>{{ worldBookPreviewStatus }}</span>
        </div>
        <el-input
          v-model="worldBookPreviewText"
          data-testid="world-book-preview-input"
          type="textarea"
          :rows="dense ? 2 : 3"
          resize="none"
          placeholder="输入最近对话测试"
        />
        <div v-if="worldBookPreviewMatches.length" class="world-preview-list">
          <button
            v-for="match in worldBookPreviewMatches"
            :key="match.entry.id"
            type="button"
            class="world-preview-item"
            @click="focusWorldEntryFromPreview(match.entry)"
          >
            <span>{{ match.entry.title || '未命名条目' }}</span>
            <small>{{ match.reason }}</small>
          </button>
        </div>
        <div v-else class="world-preview-empty">{{ worldBookPreviewEmptyLabel }}</div>
      </div>

      <div class="world-entry-create">
        <el-input v-model="worldEntryDraft.title" size="small" placeholder="条目名称" />
        <el-input v-model="worldEntryDraft.keys" size="small" placeholder="关键词，用逗号分隔" />
        <el-button size="small" type="primary" plain :disabled="!worldEntryDraft.title.trim() && !worldEntryDraft.content.trim()" @click="addWorldEntry">添加</el-button>
      </div>
      <el-input v-model="worldEntryDraft.content" class="world-entry-draft-content" type="textarea" :rows="2" resize="none" placeholder="触发后插入的内容" />

      <template v-if="filteredWorldEntries.length">
        <div class="world-entry-list">
          <article v-for="entry in pagedWorldEntries" :key="entry.id" class="world-entry">
            <div class="world-entry-head">
              <el-checkbox :model-value="isWorldEntrySelected(entry.id)" @change="(checked: boolean) => setWorldEntrySelected(entry.id, checked)" />
              <el-switch v-model="entry.enabled" size="small" />
              <el-input v-model="entry.title" size="small" placeholder="条目名称" />
              <el-input-number v-model="entry.priority" size="small" :min="0" :max="99" controls-position="right" />
              <el-button size="small" text type="danger" @click="removeWorldEntry(entry.id)">删除</el-button>
            </div>
            <el-input :model-value="entry.keys.join(', ')" size="small" placeholder="关键词" @update:model-value="(value: string) => updateWorldEntryKeys(entry.id, value)" />
            <el-input :model-value="entry.secondaryKeys.join(', ')" size="small" placeholder="二级关键词" @update:model-value="(value: string) => updateWorldEntrySecondaryKeys(entry.id, value)" />
            <div class="world-entry-options">
              <label>
                <span>顺序</span>
                <el-input-number v-model="entry.insertionOrder" size="small" :min="-999" :max="999" controls-position="right" />
              </label>
              <label>
                <span>概率</span>
                <el-input-number v-model="entry.probability" size="small" :min="0" :max="100" controls-position="right" />
              </label>
              <el-switch v-model="entry.constant" size="small" inline-prompt active-text="常驻" inactive-text="常驻" />
              <el-switch v-model="entry.selective" size="small" inline-prompt active-text="二级" inactive-text="二级" />
              <el-switch v-model="entry.caseSensitive" size="small" inline-prompt active-text="大小写" inactive-text="大小写" />
              <el-switch v-model="entry.matchWholeWords" size="small" inline-prompt active-text="整词" inactive-text="整词" />
            </div>
            <el-input v-model="entry.content" type="textarea" :rows="dense ? 2 : 3" resize="none" placeholder="内容" />
          </article>
        </div>
        <div v-if="worldBookTotalPages > 1" class="world-pager">
          <span>第 {{ worldBookPage }} / {{ worldBookTotalPages }} 页</span>
          <div>
            <el-button size="small" plain :disabled="worldBookPage <= 1" @click="goWorldBookPage(-1)">上一页</el-button>
            <el-button size="small" plain :disabled="worldBookPage >= worldBookTotalPages" @click="goWorldBookPage(1)">下一页</el-button>
          </div>
        </div>
      </template>
      <el-empty v-else :description="worldBookModel.entries.length ? '无匹配条目' : '暂无条目'" :image-size="48" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { DEFAULT_DAILY_PROMPT, DEFAULT_WORK_PROMPT, useWorkspaceStore } from '@/stores/workspaceStore'
import type { WorkspacePromptEngineering, WorkspacePromptMode, WorkspaceRoleCard, WorkspaceWorldBook, WorkspaceWorldBookEntry } from '@/../shared/workspace'

withDefaults(defineProps<{
  showMode?: boolean
  dense?: boolean
}>(), {
  showMode: true,
  dense: false,
})

const workspaceStore = useWorkspaceStore()
let syncingPromptContext = false

const roleCardModel = reactive<WorkspaceRoleCard>({
  enabled: true,
  name: '',
  personality: '',
  scenario: '',
  instructions: '',
  firstMessage: '',
})
const roleCardJson = ref('')
const roleCardJsonError = ref('')
const promptEngineeringModel = reactive<WorkspacePromptEngineering>({
  workPrompt: DEFAULT_WORK_PROMPT,
  dailyPrompt: DEFAULT_DAILY_PROMPT,
})
const worldBookModel = reactive<WorkspaceWorldBook>({
  enabled: false,
  scanDepth: 8,
  maxEntries: 8,
  budgetTokens: 1200,
  entries: [],
})
const worldEntryDraft = reactive({ title: '', keys: '', content: '' })
const roleCardFileInput = ref<HTMLInputElement | null>(null)
const worldBookJson = ref('')
const worldBookJsonError = ref('')
const worldBookFileInput = ref<HTMLInputElement | null>(null)
const worldBookImportMode = ref<'replace' | 'merge'>('replace')
const worldBookStateFilter = ref<'all' | 'enabled' | 'disabled'>('all')
const worldBookSearch = ref('')
const worldBookPreviewText = ref('')
const selectedWorldEntryIds = ref<string[]>([])
const worldBookPage = ref(1)
const WORLD_ENTRY_PAGE_SIZE = 40

interface WorldBookPreviewMatch {
  entry: WorkspaceWorldBookEntry
  primaryKeys: string[]
  secondaryKeys: string[]
  reason: string
  contentCharacters: number
}

const promptModeOptions: Array<{ label: string; value: WorkspacePromptMode }> = [
  { label: '自动', value: 'auto' },
  { label: '任务', value: 'work' },
  { label: '日常陪伴', value: 'daily' },
]

const worldBookStateFilterOptions: Array<{ label: string; value: 'all' | 'enabled' | 'disabled' }> = [
  { label: '全部', value: 'all' },
  { label: '启用', value: 'enabled' },
  { label: '停用', value: 'disabled' },
]

const activeWorkspaceId = computed(() => workspaceStore.activeWorkspaceId)
const workspacePromptMode = computed<WorkspacePromptMode>({
  get: () => workspaceStore.activeWorkspace.context.promptMode || 'auto',
  set: (mode) => workspaceStore.updateWorkspaceContext(activeWorkspaceId.value, { promptMode: mode }),
})

const filteredWorldEntries = computed(() => {
  const keyword = worldBookSearch.value.trim().toLowerCase()
  const entries = worldBookModel.entries.filter((entry) => {
    if (worldBookStateFilter.value === 'enabled') return entry.enabled !== false
    if (worldBookStateFilter.value === 'disabled') return entry.enabled === false
    return true
  })
  if (!keyword) return entries
  return entries.filter((entry) => [
    entry.title,
    entry.content,
    entry.keys.join(' '),
    entry.secondaryKeys.join(' '),
  ].join(' ').toLowerCase().includes(keyword))
})

const worldBookTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredWorldEntries.value.length / WORLD_ENTRY_PAGE_SIZE)),
)

const pagedWorldEntries = computed(() => {
  const page = Math.min(worldBookPage.value, worldBookTotalPages.value)
  const start = (page - 1) * WORLD_ENTRY_PAGE_SIZE
  return filteredWorldEntries.value.slice(start, start + WORLD_ENTRY_PAGE_SIZE)
})

const worldEntryRangeLabel = computed(() => {
  const total = filteredWorldEntries.value.length
  if (!total) return `0 / ${worldBookModel.entries.length}`
  const page = Math.min(worldBookPage.value, worldBookTotalPages.value)
  const start = (page - 1) * WORLD_ENTRY_PAGE_SIZE + 1
  const end = Math.min(total, start + pagedWorldEntries.value.length - 1)
  return `${start}-${end} / ${total} / ${worldBookModel.entries.length}`
})

const selectedWorldEntryIdSet = computed(() => new Set(selectedWorldEntryIds.value))

const selectedWorldEntries = computed(() =>
  worldBookModel.entries.filter((entry) => selectedWorldEntryIdSet.value.has(entry.id)),
)

const allFilteredWorldEntriesSelected = computed(() =>
  filteredWorldEntries.value.length > 0
  && filteredWorldEntries.value.every((entry) => selectedWorldEntryIdSet.value.has(entry.id)),
)

const isWorldEntrySelectionPartial = computed(() => {
  if (!filteredWorldEntries.value.length || allFilteredWorldEntriesSelected.value) return false
  return filteredWorldEntries.value.some((entry) => selectedWorldEntryIdSet.value.has(entry.id))
})

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const getRegexKey = (key: string, caseSensitive: boolean) => {
  const trimmed = key.trim()
  if (!trimmed.startsWith('/') || trimmed.length < 3) return null
  const lastSlash = trimmed.lastIndexOf('/')
  if (lastSlash <= 0) return null
  const pattern = trimmed.slice(1, lastSlash)
  const rawFlags = trimmed.slice(lastSlash + 1)
  try {
    const flags = new Set(rawFlags.replace(/g/g, '').split('').filter(Boolean))
    if (!caseSensitive) flags.add('i')
    if (!flags.has('u') && !flags.has('v')) flags.add('u')
    return new RegExp(pattern, [...flags].join(''))
  } catch {
    return null
  }
}

const worldKeyMatches = (key: string, text: string, caseSensitive: boolean, matchWholeWords: boolean) => {
  const trimmed = key.trim()
  if (!trimmed || !text) return false
  const regexKey = getRegexKey(trimmed, caseSensitive)
  if (regexKey) return regexKey.test(text)
  if (matchWholeWords) {
    try {
      const flags = caseSensitive ? 'u' : 'iu'
      return new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRegExp(trimmed)}(?![\\p{L}\\p{N}_])`, flags).test(text)
    } catch {
      return false
    }
  }
  if (caseSensitive) return text.includes(trimmed)
  return text.toLowerCase().includes(trimmed.toLowerCase())
}

const matchWorldKeys = (keys: string[], text: string, entry: WorkspaceWorldBookEntry) =>
  keys
    .map((key) => key.trim())
    .filter((key) => worldKeyMatches(key, text, entry.caseSensitive, entry.matchWholeWords))
    .slice(0, 3)

const getWorldBookScanText = (value: string, depth: number) => {
  const chunks = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (chunks.length <= 1) return value.trim()
  return chunks.slice(-Math.max(1, depth)).join('\n')
}

const createWorldBookPreviewMatch = (entry: WorkspaceWorldBookEntry, text: string): WorldBookPreviewMatch | null => {
  if (entry.enabled === false || entry.probability <= 0 || !entry.content.trim()) return null
  if (entry.constant) {
    return {
      entry,
      primaryKeys: [],
      secondaryKeys: [],
      reason: '常驻',
      contentCharacters: entry.content.length,
    }
  }
  const primaryKeys = matchWorldKeys(entry.keys, text, entry)
  if (!primaryKeys.length) return null
  const secondaryKeys = matchWorldKeys(entry.secondaryKeys, text, entry)
  if (entry.selective && entry.secondaryKeys.length && !secondaryKeys.length) return null
  const reason = entry.selective && entry.secondaryKeys.length
    ? `${primaryKeys[0]} + ${secondaryKeys[0]}`
    : primaryKeys[0]
  return {
    entry,
    primaryKeys,
    secondaryKeys,
    reason,
    contentCharacters: entry.content.length,
  }
}

const worldBookPreviewScanText = computed(() => getWorldBookScanText(worldBookPreviewText.value, worldBookModel.scanDepth))

const worldBookPreviewMatches = computed(() => {
  if (!worldBookModel.enabled) return []
  const text = worldBookPreviewScanText.value
  const budgetCharacters = Math.max(1, worldBookModel.budgetTokens * 4)
  const matches = worldBookModel.entries
    .map((entry) => createWorldBookPreviewMatch(entry, text))
    .filter((match): match is WorldBookPreviewMatch => Boolean(match))
    .sort((a, b) =>
      b.entry.priority - a.entry.priority ||
      a.entry.insertionOrder - b.entry.insertionOrder ||
      a.entry.title.localeCompare(b.entry.title, 'zh-Hans-CN'),
    )
  const limited: WorldBookPreviewMatch[] = []
  let usedCharacters = 0
  for (const match of matches) {
    if (limited.length >= worldBookModel.maxEntries) break
    if (limited.length > 0 && usedCharacters + match.contentCharacters > budgetCharacters) break
    limited.push(match)
    usedCharacters += match.contentCharacters
  }
  return limited
})

const worldBookPreviewStatus = computed(() => {
  if (!worldBookModel.enabled) return '已关闭'
  const usedCharacters = worldBookPreviewMatches.value.reduce((total, match) => total + match.contentCharacters, 0)
  return `命中 ${worldBookPreviewMatches.value.length} 条 · ${usedCharacters} 字`
})

const worldBookPreviewEmptyLabel = computed(() => {
  if (!worldBookModel.enabled) return '世界书已关闭'
  return worldBookPreviewText.value.trim() ? '未命中' : '等待输入'
})

const parseWorldKeys = (value: string) =>
  splitWorldKeys(value)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 24)

const splitWorldKeys = (value: string) => {
  const parts: string[] = []
  let current = ''
  let inRegex = false
  let escaped = false
  for (const char of value) {
    if (escaped) {
      current += char
      escaped = false
      continue
    }
    if (inRegex) {
      current += char
      if (char === '\\') {
        escaped = true
      } else if (char === '/') {
        inRegex = false
      }
      continue
    }
    if (char === '/' && !current.trim()) {
      current += char
      inRegex = true
      continue
    }
    if (char === ',' || char === '，' || char === '\n') {
      parts.push(current)
      current = ''
      continue
    }
    current += char
  }
  parts.push(current)
  return parts
}

const createWorldEntryId = () => `world_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`

const createEmptyRoleCard = (enabled = true): WorkspaceRoleCard => ({
  enabled,
  name: '',
  personality: '',
  scenario: '',
  instructions: '',
  firstMessage: '',
})

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)

const readString = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string') return value
  }
  return ''
}

const readIdentifier = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  }
  return ''
}

const readNumber = (source: Record<string, unknown>, keys: string[], fallback = 0) => {
  for (const key of keys) {
    const value = source[key]
    const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : Number.NaN
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

const readBoolean = (source: Record<string, unknown>, keys: string[], fallback = false) => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'boolean') return value
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase()
      if (['1', 'true', 'yes', 'on', 'enabled'].includes(normalized)) return true
      if (['0', 'false', 'no', 'off', 'disabled'].includes(normalized)) return false
    }
  }
  return fallback
}

const readStringList = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key]
    if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean).slice(0, 24)
    if (typeof value === 'string') return parseWorldKeys(value)
  }
  return []
}

const normalizeRoleCardJsonObject = (source: Record<string, unknown>, currentEnabled = true): WorkspaceRoleCard => {
  const data = isRecord(source.data) ? source.data : source
  const description = readString(data, ['description'])
  const explicitPersonality = readString(data, ['personality'])
  const systemPrompt = readString(data, ['system_prompt', 'systemPrompt'])
  const postHistoryInstructions = readString(data, ['post_history_instructions', 'postHistoryInstructions'])
  const instructions = [
    readString(data, ['instructions']),
    systemPrompt,
    postHistoryInstructions,
    description && explicitPersonality ? description : '',
  ].filter(Boolean).join('\n\n')
  return {
    enabled: typeof data.enabled === 'boolean' ? data.enabled : currentEnabled,
    name: readString(data, ['name', 'character_name', 'characterName']),
    personality: explicitPersonality || description,
    scenario: readString(data, ['scenario']),
    instructions,
    firstMessage: readString(data, ['firstMessage', 'first_message', 'first_mes', 'firstMes']),
  }
}

const cloneRoleCard = (source: WorkspaceRoleCard): WorkspaceRoleCard => ({
  enabled: source.enabled !== false,
  name: source.name || '',
  personality: source.personality || '',
  scenario: source.scenario || '',
  instructions: source.instructions || '',
  firstMessage: source.firstMessage || '',
})

const hasRoleCardContent = (roleCard: WorkspaceRoleCard) =>
  Boolean(roleCard.name.trim() || roleCard.personality.trim() || roleCard.scenario.trim() || roleCard.instructions.trim() || roleCard.firstMessage.trim())

const roleCardToJson = (roleCard: WorkspaceRoleCard) => {
  if (!hasRoleCardContent(roleCard)) return ''
  return JSON.stringify({
    ...(roleCard.name ? { name: roleCard.name } : {}),
    ...(roleCard.personality ? { personality: roleCard.personality } : {}),
    ...(roleCard.scenario ? { scenario: roleCard.scenario } : {}),
    ...(roleCard.instructions ? { instructions: roleCard.instructions } : {}),
    ...(roleCard.firstMessage ? { firstMessage: roleCard.firstMessage } : {}),
  }, null, 2)
}

const clonePromptEngineering = (source?: Partial<WorkspacePromptEngineering>): WorkspacePromptEngineering => ({
  workPrompt: source?.workPrompt?.trim() || DEFAULT_WORK_PROMPT,
  dailyPrompt: source?.dailyPrompt?.trim() || DEFAULT_DAILY_PROMPT,
})

const cloneWorldEntry = (entry: WorkspaceWorldBookEntry): WorkspaceWorldBookEntry => ({
  id: entry.id || createWorldEntryId(),
  title: entry.title || '',
  keys: Array.isArray(entry.keys) ? entry.keys.map(String).filter(Boolean) : [],
  secondaryKeys: Array.isArray(entry.secondaryKeys) ? entry.secondaryKeys.map(String).filter(Boolean) : [],
  content: entry.content || '',
  enabled: entry.enabled !== false,
  priority: Number.isFinite(Number(entry.priority)) ? Number(entry.priority) : 0,
  insertionOrder: Number.isFinite(Number(entry.insertionOrder)) ? Number(entry.insertionOrder) : 0,
  constant: entry.constant === true,
  selective: entry.selective === true,
  caseSensitive: entry.caseSensitive === true,
  matchWholeWords: entry.matchWholeWords === true,
  probability: Math.max(0, Math.min(100, Number.isFinite(Number(entry.probability)) ? Number(entry.probability) : 100)),
})

const cloneWorldBook = (source: WorkspaceWorldBook): WorkspaceWorldBook => ({
  enabled: source.enabled === true,
  scanDepth: Math.max(1, Math.min(32, Math.round(Number(source.scanDepth) || 8))),
  maxEntries: Math.max(1, Math.min(64, Math.round(Number(source.maxEntries) || 8))),
  budgetTokens: Math.max(128, Math.min(32000, Math.round(Number(source.budgetTokens) || 1200))),
  entries: Array.isArray(source.entries) ? source.entries.map(cloneWorldEntry) : [],
})

const syncPromptModelsFromWorkspace = () => {
  syncingPromptContext = true
  selectedWorldEntryIds.value = []
  worldBookPreviewText.value = ''
  Object.assign(promptEngineeringModel, clonePromptEngineering(workspaceStore.activeWorkspace.context.promptEngineering))
  Object.assign(roleCardModel, cloneRoleCard(workspaceStore.activeWorkspace.context.roleCard))
  roleCardJson.value = roleCardToJson(roleCardModel)
  roleCardJsonError.value = ''
  const worldBook = cloneWorldBook(workspaceStore.activeWorkspace.context.worldBook)
  worldBookModel.enabled = worldBook.enabled
  worldBookModel.scanDepth = worldBook.scanDepth
  worldBookModel.maxEntries = worldBook.maxEntries
  worldBookModel.budgetTokens = worldBook.budgetTokens
  worldBookModel.entries = worldBook.entries
  worldBookJson.value = ''
  worldBookJsonError.value = ''
  window.setTimeout(() => {
    syncingPromptContext = false
  }, 0)
}

const persistPromptContext = () => {
  if (syncingPromptContext) return
  if (roleCardJsonError.value) return
  workspaceStore.updateWorkspaceContext(activeWorkspaceId.value, {
    promptEngineering: clonePromptEngineering(promptEngineeringModel),
    roleCard: cloneRoleCard(roleCardModel),
    worldBook: cloneWorldBook(worldBookModel),
  })
}

const resetBasePrompts = () => {
  promptEngineeringModel.workPrompt = DEFAULT_WORK_PROMPT
  promptEngineeringModel.dailyPrompt = DEFAULT_DAILY_PROMPT
}

const setRoleCardJsonText = (value: string) => {
  if (roleCardJson.value === value) {
    applyRoleCardJson(value)
    return
  }
  roleCardJson.value = value
}

const openRoleCardFilePicker = () => {
  roleCardFileInput.value?.click()
}

const importRoleCardFile = async (event: Event) => {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  try {
    setRoleCardJsonText(await file.text())
  } catch {
    roleCardJsonError.value = '无法读取 JSON 文件'
  } finally {
    if (input) input.value = ''
  }
}

const exportJsonFile = (payload: unknown, filename: string) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

const exportRoleCardFile = () => {
  if (!hasRoleCardContent(roleCardModel) || roleCardJsonError.value) return
  const payload = {
    ...(roleCardModel.name ? { name: roleCardModel.name } : {}),
    ...(roleCardModel.personality ? { personality: roleCardModel.personality } : {}),
    ...(roleCardModel.scenario ? { scenario: roleCardModel.scenario } : {}),
    ...(roleCardModel.instructions ? { instructions: roleCardModel.instructions } : {}),
    ...(roleCardModel.firstMessage ? { firstMessage: roleCardModel.firstMessage } : {}),
    ...(worldBookModel.entries.length ? { character_book: cloneWorldBook(worldBookModel) } : {}),
  }
  exportJsonFile(payload, `${activeWorkspaceId.value || 'workspace'}-role-card.json`)
}

const addWorldEntry = () => {
  const title = worldEntryDraft.title.trim()
  const content = worldEntryDraft.content.trim()
  if (!title && !content) return
  worldBookModel.enabled = true
  worldBookModel.entries.unshift({
    id: createWorldEntryId(),
    title: title || '未命名条目',
    keys: parseWorldKeys(worldEntryDraft.keys),
    secondaryKeys: [],
    content,
    enabled: true,
    priority: 0,
    insertionOrder: worldBookModel.entries.length,
    constant: false,
    selective: false,
    caseSensitive: false,
    matchWholeWords: false,
    probability: 100,
  })
  worldEntryDraft.title = ''
  worldEntryDraft.keys = ''
  worldEntryDraft.content = ''
}

const removeWorldEntry = (id: string) => {
  worldBookModel.entries = worldBookModel.entries.filter((entry) => entry.id !== id)
  selectedWorldEntryIds.value = selectedWorldEntryIds.value.filter((entryId) => entryId !== id)
}

const updateWorldEntryKeys = (id: string, value: string) => {
  const entry = worldBookModel.entries.find((item) => item.id === id)
  if (entry) entry.keys = parseWorldKeys(value)
}

const updateWorldEntrySecondaryKeys = (id: string, value: string) => {
  const entry = worldBookModel.entries.find((item) => item.id === id)
  if (entry) entry.secondaryKeys = parseWorldKeys(value)
}

const resolveImportedWorldBook = (source: unknown): Record<string, unknown> | null => {
  if (Array.isArray(source)) return { entries: source }
  if (!isRecord(source)) return null
  if (isRecord(source.data) && isRecord(source.data.character_book)) return source.data.character_book
  if (isRecord(source.character_book)) return source.character_book
  if (isRecord(source.worldBook)) return source.worldBook
  if (isRecord(source.lorebook)) return source.lorebook
  if (isRecord(source.world_info)) return source.world_info
  if (isRecord(source.worldInfo)) return source.worldInfo
  return source
}

const resolveEmbeddedWorldBook = (source: unknown): Record<string, unknown> | null => {
  if (!isRecord(source)) return null
  const data = isRecord(source.data) ? source.data : null
  if (data && isRecord(data.character_book)) return data.character_book
  if (data && isRecord(data.worldBook)) return data.worldBook
  if (data && isRecord(data.lorebook)) return data.lorebook
  if (data && isRecord(data.world_info)) return data.world_info
  if (data && isRecord(data.worldInfo)) return data.worldInfo
  if (isRecord(source.character_book)) return source.character_book
  if (isRecord(source.worldBook)) return source.worldBook
  if (isRecord(source.lorebook)) return source.lorebook
  if (isRecord(source.world_info)) return source.world_info
  if (isRecord(source.worldInfo)) return source.worldInfo
  return null
}

const resolveImportedEntries = (book: Record<string, unknown>) => {
  const rawEntries = book.entries ?? book.items ?? book.worldEntries ?? book.world_entries
  if (Array.isArray(rawEntries)) return rawEntries
  if (isRecord(rawEntries)) {
    return Object.entries(rawEntries).map(([id, value]) =>
      isRecord(value) && !('id' in value) && !('uid' in value) ? { id, ...value } : value,
    )
  }
  return []
}

const normalizeImportedWorldEntry = (raw: unknown, index: number): WorkspaceWorldBookEntry | null => {
  if (!isRecord(raw)) return null
  const extensions = isRecord(raw.extensions) ? raw.extensions : {}
  const content = readString(raw, ['content', 'entry', 'text', 'value', 'prompt']).trim()
  if (!content) return null
  const disabled = readBoolean(raw, ['disable', 'disabled'], false)
  const order = readNumber(raw, ['insertionOrder', 'insertion_order', 'order'], index)
  const secondaryKeys = readStringList(raw, ['secondaryKeys', 'secondary_keys', 'keysecondary', 'secondary', 'secondaryKeywords', 'secondary_keywords'])
  const id = readIdentifier(raw, ['id', 'uid'])
  return {
    id: id || createWorldEntryId(),
    title: readString(raw, ['title', 'comment', 'name', 'memo', 'displayName']) || id || `条目 ${index + 1}`,
    keys: readStringList(raw, ['keys', 'key', 'primaryKeys', 'primary_keys', 'keywords', 'triggers']),
    secondaryKeys,
    content,
    enabled: raw.enabled === false ? false : !disabled,
    priority: readNumber(raw, ['priority'], 0),
    insertionOrder: order,
    constant: readBoolean(raw, ['constant'], false),
    selective: readBoolean(raw, ['selective'], secondaryKeys.length > 0),
    caseSensitive: readBoolean(raw, ['caseSensitive', 'case_sensitive'], false) || readBoolean(extensions, ['case_sensitive'], false),
    matchWholeWords: readBoolean(raw, ['matchWholeWords', 'match_whole_words'], false) || readBoolean(extensions, ['match_whole_words'], false),
    probability: readBoolean(raw, ['useProbability', 'use_probability'], true) === false
      ? 100
      : Math.max(0, Math.min(100, readNumber(raw, ['probability'], 100))),
  }
}

const worldEntrySignature = (entry: WorkspaceWorldBookEntry) =>
  [
    entry.title.trim(),
    entry.content.trim(),
    entry.keys.join('\u0001'),
    entry.secondaryKeys.join('\u0001'),
  ].join('\u0002')

const mergeWorldEntries = (current: WorkspaceWorldBookEntry[], imported: WorkspaceWorldBookEntry[]) => {
  const usedIds = new Set(current.map((entry) => entry.id))
  const usedSignatures = new Set(current.map(worldEntrySignature))
  const merged = [...current]
  for (const entry of imported) {
    const signature = worldEntrySignature(entry)
    if (usedSignatures.has(signature)) continue
    const nextEntry = usedIds.has(entry.id) ? { ...entry, id: createWorldEntryId() } : entry
    merged.push(nextEntry)
    usedIds.add(nextEntry.id)
    usedSignatures.add(signature)
  }
  return merged
}

const isWorldEntrySelected = (id: string) => selectedWorldEntryIdSet.value.has(id)

const setWorldEntrySelected = (id: string, selected: boolean) => {
  const ids = new Set(selectedWorldEntryIds.value)
  if (selected) ids.add(id)
  else ids.delete(id)
  selectedWorldEntryIds.value = [...ids]
}

const toggleFilteredWorldEntrySelection = (selected: boolean) => {
  const ids = new Set(selectedWorldEntryIds.value)
  for (const entry of filteredWorldEntries.value) {
    if (selected) ids.add(entry.id)
    else ids.delete(entry.id)
  }
  selectedWorldEntryIds.value = [...ids]
}

const batchSetWorldEntriesEnabled = (enabled: boolean) => {
  if (!selectedWorldEntryIds.value.length) return
  const ids = selectedWorldEntryIdSet.value
  for (const entry of worldBookModel.entries) {
    if (ids.has(entry.id)) entry.enabled = enabled
  }
}

const removeSelectedWorldEntries = () => {
  if (!selectedWorldEntryIds.value.length) return
  const ids = selectedWorldEntryIdSet.value
  worldBookModel.entries = worldBookModel.entries.filter((entry) => !ids.has(entry.id))
  selectedWorldEntryIds.value = []
  if (worldBookPage.value > worldBookTotalPages.value) {
    worldBookPage.value = worldBookTotalPages.value
  }
}

const goWorldBookPage = (delta: number) => {
  worldBookPage.value = Math.max(1, Math.min(worldBookTotalPages.value, worldBookPage.value + delta))
}

const focusWorldEntryFromPreview = (entry: WorkspaceWorldBookEntry) => {
  worldBookStateFilter.value = 'all'
  worldBookSearch.value = entry.title || entry.keys[0] || entry.content.slice(0, 20)
  const index = filteredWorldEntries.value.findIndex((item) => item.id === entry.id)
  if (index >= 0) worldBookPage.value = Math.floor(index / WORLD_ENTRY_PAGE_SIZE) + 1
}

const applyImportedWorldBook = (book: Record<string, unknown>, mode: 'replace' | 'merge') => {
  const entries = resolveImportedEntries(book)
    .map(normalizeImportedWorldEntry)
    .filter((entry): entry is WorkspaceWorldBookEntry => Boolean(entry))
  if (!entries.length) return false
  worldBookModel.enabled = true
  worldBookModel.scanDepth = Math.max(1, Math.min(32, Math.round(readNumber(book, ['scanDepth', 'scan_depth', 'depth'], worldBookModel.scanDepth))))
  worldBookModel.maxEntries = Math.max(1, Math.min(64, Math.round(readNumber(book, ['maxEntries', 'max_entries'], Math.max(worldBookModel.maxEntries, entries.length)))))
  worldBookModel.budgetTokens = Math.max(128, Math.min(32000, Math.round(readNumber(book, ['budgetTokens', 'budget_tokens', 'token_budget'], worldBookModel.budgetTokens))))
  worldBookModel.entries = mode === 'merge'
    ? mergeWorldEntries(worldBookModel.entries, entries)
    : entries
  if (mode === 'replace') selectedWorldEntryIds.value = []
  return true
}

const importWorldBookFromText = (value: string) => {
  const trimmed = value.trim()
  if (!trimmed) return
  try {
    const parsed = JSON.parse(trimmed) as unknown
    const book = resolveImportedWorldBook(parsed)
    if (!book) {
      worldBookJsonError.value = '世界书 JSON 需要是对象'
      return
    }
    if (!applyImportedWorldBook(book, worldBookImportMode.value)) {
      worldBookJsonError.value = '没有找到可导入的世界书条目'
      return
    }
    worldBookJsonError.value = ''
    worldBookJson.value = ''
  } catch {
    worldBookJsonError.value = 'JSON 格式不正确'
  }
}

const importWorldBookJson = () => {
  importWorldBookFromText(worldBookJson.value)
}

const openWorldBookFilePicker = () => {
  worldBookFileInput.value?.click()
}

const importWorldBookFile = async (event: Event) => {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  try {
    importWorldBookFromText(await file.text())
  } catch {
    worldBookJsonError.value = '无法读取 JSON 文件'
  } finally {
    if (input) input.value = ''
  }
}

const exportWorldBookFile = () => {
  if (!worldBookModel.entries.length) return
  exportWorldBookEntries(worldBookModel.entries, 'world-book')
}

const exportSelectedWorldBookFile = () => {
  if (!selectedWorldEntries.value.length) return
  exportWorldBookEntries(selectedWorldEntries.value, 'world-book-selected')
}

const exportWorldBookEntries = (entries: WorkspaceWorldBookEntry[], suffix: string) => {
  exportJsonFile({
    worldBook: {
      ...cloneWorldBook(worldBookModel),
      entries: entries.map(cloneWorldEntry),
    },
  }, `${activeWorkspaceId.value || 'workspace'}-${suffix}.json`)
}

const applyRoleCardJson = (value: string) => {
  if (syncingPromptContext) return
  const trimmed = value.trim()
  if (!trimmed) {
    roleCardJsonError.value = ''
    Object.assign(roleCardModel, createEmptyRoleCard(roleCardModel.enabled))
    return
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (!isRecord(parsed)) {
      roleCardJsonError.value = '角色卡 JSON 需要是一个对象'
      return
    }
    roleCardJsonError.value = ''
    Object.assign(roleCardModel, normalizeRoleCardJsonObject(parsed, roleCardModel.enabled))
    const embeddedWorldBook = resolveEmbeddedWorldBook(parsed)
    if (embeddedWorldBook) {
      applyImportedWorldBook(embeddedWorldBook, worldBookModel.entries.length ? 'merge' : 'replace')
    }
  } catch {
    roleCardJsonError.value = 'JSON 格式不正确，已保留上一次有效角色卡'
  }
}

syncPromptModelsFromWorkspace()
watch(activeWorkspaceId, syncPromptModelsFromWorkspace)
watch([worldBookSearch, worldBookStateFilter], () => {
  worldBookPage.value = 1
})
watch(() => filteredWorldEntries.value.length, () => {
  worldBookPage.value = Math.max(1, Math.min(worldBookPage.value, worldBookTotalPages.value))
  const validIds = new Set(worldBookModel.entries.map((entry) => entry.id))
  selectedWorldEntryIds.value = selectedWorldEntryIds.value.filter((id) => validIds.has(id))
})
watch(promptEngineeringModel, persistPromptContext, { deep: true })
watch(roleCardModel, persistPromptContext, { deep: true })
watch(roleCardJson, applyRoleCardJson)
watch(worldBookModel, persistPromptContext, { deep: true })
</script>

<style scoped>
.workspace-prompt-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.prompt-section {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 10px;
  background: var(--yui-surface-raised, #fff);
  padding: 14px;
}

.is-dense .prompt-section {
  padding: 12px;
}

.prompt-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.prompt-section-header h3 {
  margin: 0;
  color: var(--yui-text, #111827);
  font-size: 14px;
  font-weight: 820;
  letter-spacing: 0;
}

.section-actions {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.mode-segment {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 10px;
  background: var(--yui-surface-muted, #f8fafc);
  padding: 4px;
}

.mode-segment button {
  min-width: 0;
  min-height: 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--yui-muted, #64748b);
  cursor: pointer;
  font-size: 13px;
  font-weight: 760;
}

.mode-segment button:hover,
.mode-segment button:focus-visible {
  background: var(--yui-surface-raised, #fff);
  color: var(--yui-text, #111827);
  outline: none;
}

.mode-segment button.active {
  background: var(--yui-surface-raised, #fff);
  color: var(--yui-accent, #047857);
  box-shadow: var(--yui-shadow-card, 0 6px 16px rgba(15, 23, 42, 0.08));
}

.prompt-form {
  min-width: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.prompt-field-error {
  margin: -6px 0 0;
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.5;
}

.world-entry-create {
  display: grid;
  grid-template-columns: minmax(90px, 0.8fr) minmax(130px, 1fr) auto;
  gap: 8px;
}

.world-book-options,
.world-entry-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(94px, 1fr));
  align-items: center;
  gap: 8px;
}

.world-book-options label,
.world-entry-options label {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.world-book-options span,
.world-entry-options span {
  color: var(--yui-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
}

.world-toolbar {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(170px, 210px) auto;
  align-items: center;
  gap: 8px;
}

.world-import-mode,
.world-state-filter {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.world-state-filter {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.world-entry-count {
  min-width: 56px;
  color: var(--yui-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
  text-align: right;
  white-space: nowrap;
}

.world-import-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
}

.world-import-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 132px;
}

.hidden-file-input {
  display: none;
}

.world-batch-bar {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 10px;
  background: var(--yui-surface-muted, #f8fafc);
  padding: 8px 10px;
}

.world-batch-bar span {
  color: var(--yui-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
}

.world-entry-draft-content {
  margin-top: -4px;
}

.world-preview {
  display: grid;
  min-width: 0;
  gap: 8px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 10px;
  background: var(--yui-surface-muted, #f8fafc);
  padding: 10px;
}

.world-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--yui-text, #111827);
  font-size: 12px;
  font-weight: 820;
}

.world-preview-head span:last-child {
  color: var(--yui-muted, #64748b);
  font-weight: 760;
  white-space: nowrap;
}

.world-preview-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.world-preview-item {
  display: inline-flex;
  min-width: 0;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 8px;
  background: var(--yui-surface-raised, #fff);
  color: var(--yui-text, #111827);
  cursor: pointer;
  padding: 5px 8px;
  font-size: 12px;
  font-weight: 760;
}

.world-preview-item:hover,
.world-preview-item:focus-visible {
  border-color: color-mix(in srgb, var(--yui-accent, #047857) 38%, var(--yui-border, rgba(226, 232, 240, 0.9)));
  color: var(--yui-accent, #047857);
  outline: none;
}

.world-preview-item span,
.world-preview-item small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.world-preview-item small {
  color: var(--yui-muted, #64748b);
  font-size: 11px;
  font-weight: 700;
}

.world-preview-empty {
  color: var(--yui-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
}

.world-entry-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.world-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--yui-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
}

.world-pager > div {
  display: inline-flex;
  gap: 8px;
}

.world-entry {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--yui-border, rgba(226, 232, 240, 0.9));
  border-radius: 10px;
  background: var(--yui-surface-muted, #f8fafc);
  padding: 10px;
}

.world-entry-head {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) 92px auto;
  align-items: center;
  gap: 8px;
}

:deep(.el-form-item) {
  margin-bottom: 12px;
}

:deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

@media (max-width: 720px) {
  .form-grid,
  .world-entry-create,
  .world-toolbar,
  .world-import-row,
  .world-entry-head {
    grid-template-columns: 1fr;
  }

  .world-entry-count {
    text-align: left;
  }

  .world-import-actions {
    align-items: stretch;
    flex-direction: column;
    min-width: 0;
  }

  .world-pager {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>

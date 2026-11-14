<template>
  <div class="workspace-prompt-editor" :class="{ 'is-dense': dense }">
    <section v-if="showMode" v-show="section === 'all' || section === 'behavior'" class="prompt-section">
      <header class="prompt-section-header">
        <h3>{{ t('promptPanel.mode.title') }}</h3>
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

    <section v-show="section === 'all' || section === 'behavior'" class="prompt-section">
      <header class="prompt-section-header">
        <h3>{{ t('promptPanel.base.title') }}</h3>
        <el-button size="small" text @click="resetBasePrompts">{{ t('promptPanel.base.reset') }}</el-button>
      </header>
      <el-form class="prompt-form" label-position="top" @submit.prevent>
        <el-form-item :label="t('promptPanel.base.workLabel')">
          <el-input v-model="promptEngineeringModel.workPrompt" type="textarea" :rows="dense ? 4 : 6" resize="none" />
        </el-form-item>
        <el-form-item :label="t('promptPanel.base.dailyLabel')">
          <el-input v-model="promptEngineeringModel.dailyPrompt" type="textarea" :rows="dense ? 4 : 6" resize="none" />
        </el-form-item>
      </el-form>
    </section>

    <section v-show="section === 'all' || section === 'role'" class="prompt-section role-section">
      <header class="prompt-section-header">
        <h3>{{ copy('工作区角色卡', 'Workspace character card') }}</h3>
        <div class="section-actions">
          <input ref="roleCardFileInput" class="hidden-file-input" type="file" accept=".json,application/json" @change="importRoleCardFile">
          <el-button size="small" plain :title="copy('导入 V1 / V2 / V3 角色卡 JSON', 'Import V1 / V2 / V3 character card JSON')" @click="openRoleCardFilePicker">{{ t('promptPanel.roleCard.import') }}</el-button>
          <el-button size="small" plain :title="copy('保留导入卡的原格式与扩展字段；新卡使用 V2', 'Keep the imported JSON format and extension fields; new cards use V2')" :disabled="!hasRoleCardContent(roleCardModel)" @click="exportRoleCardFile">{{ t('promptPanel.roleCard.export') }}</el-button>
          <el-switch v-model="roleCardModel.enabled" size="small" :aria-label="copy('启用工作区角色卡', 'Enable workspace character card')" />
        </div>
      </header>
      <el-form class="prompt-form role-fields" label-position="top" @submit.prevent>
        <el-form-item class="role-field-wide" :label="copy('角色名称', 'Character name')">
          <el-input v-model="roleCardModel.name" :maxlength="240" :placeholder="copy('角色如何称呼自己', 'How the character introduces themselves')" />
        </el-form-item>
        <el-form-item :label="copy('身份与背景', 'Identity and background')">
          <el-input v-model="roleCardModel.description" type="textarea" :maxlength="1600" show-word-limit :rows="4" resize="vertical" :placeholder="copy('身份、经历、兴趣与知识边界', 'Identity, experiences, interests and knowledge boundaries')" />
        </el-form-item>
        <el-form-item :label="copy('性格与价值观', 'Personality and values')">
          <el-input v-model="roleCardModel.personality" type="textarea" :maxlength="1600" show-word-limit :rows="4" resize="vertical" :placeholder="copy('如何思考、做决定，以及看重什么', 'How they think, decide and what they value')" />
        </el-form-item>
        <el-form-item :label="copy('关系与情境', 'Relationship and scenario')">
          <el-input v-model="roleCardModel.scenario" type="textarea" :maxlength="1600" show-word-limit :rows="4" resize="vertical" :placeholder="copy('与用户的关系、当前场景和共同目标', 'Relationship with the user, setting and shared goals')" />
        </el-form-item>
        <el-form-item :label="copy('表达与行为边界', 'Voice and behavior')">
          <el-input v-model="roleCardModel.instructions" type="textarea" :maxlength="1600" show-word-limit :rows="4" resize="vertical" :placeholder="copy('称呼、语气、回应习惯，以及不该做的事', 'Address, tone, response habits and boundaries')" />
        </el-form-item>
        <el-form-item :label="copy('对话示例', 'Example dialogue')">
          <el-input v-model="roleCardModel.exampleDialogue" type="textarea" :maxlength="1600" show-word-limit :rows="5" resize="vertical" :placeholder="copy('用户：今天计划全乱了。\n角色：先别急，我们挑一件最重要的事重新开始。', 'User: My plans fell apart.\nCharacter: Let’s start again with the one thing that matters most.')" />
        </el-form-item>
        <el-form-item :label="copy('开场白参考', 'Greeting reference')">
          <el-input v-model="roleCardModel.firstMessage" type="textarea" :rows="5" :maxlength="500" show-word-limit resize="vertical" :placeholder="copy('用于语气参考的开场表达', 'An opening line that demonstrates the character’s voice')" />
        </el-form-item>
      </el-form>
      <details class="alternate-greetings">
        <summary>{{ copy('备用开场白', 'Alternate greetings') }} <span>{{ roleCardModel.alternateGreetings?.length || 0 }}</span></summary>
        <div class="greeting-actions">
          <el-button size="small" plain :aria-pressed="(roleCardModel.greetingIndex ?? -1) === -1" @click="roleCardModel.greetingIndex = -1">{{ (roleCardModel.greetingIndex ?? -1) === -1 ? copy('主开场已选用', 'Main greeting selected') : copy('使用主开场', 'Use main greeting') }}</el-button>
          <el-button size="small" plain :disabled="(roleCardModel.alternateGreetings?.length || 0) >= 20" @click="addGreeting">{{ copy('添加备用开场', 'Add greeting') }}</el-button>
        </div>
        <article v-for="(_, index) in roleCardModel.alternateGreetings" :key="index" class="greeting-entry">
          <header>
            <strong>{{ copy('备用开场', 'Greeting') }} {{ index + 1 }}</strong>
            <div class="greeting-actions">
              <el-button size="small" plain :aria-pressed="roleCardModel.greetingIndex === index" @click="roleCardModel.greetingIndex = index">{{ roleCardModel.greetingIndex === index ? copy('已选用', 'Selected') : copy('用作参考', 'Use as reference') }}</el-button>
              <el-button size="small" plain :disabled="index === 0" :aria-label="copy('上移备用开场', 'Move greeting up')" @click="moveGreeting(index, -1)">↑</el-button>
              <el-button size="small" plain :disabled="index === (roleCardModel.alternateGreetings?.length || 0) - 1" :aria-label="copy('下移备用开场', 'Move greeting down')" @click="moveGreeting(index, 1)">↓</el-button>
              <el-button size="small" plain @click="removeGreeting(index)">{{ copy('删除', 'Remove') }}</el-button>
            </div>
          </header>
          <el-input v-model="roleCardModel.alternateGreetings![index]" type="textarea" :rows="3" :maxlength="500" show-word-limit resize="vertical" :aria-label="`${copy('备用开场', 'Greeting')} ${index + 1}`" />
        </article>
      </details>
      <details class="role-json-editor">
        <summary>{{ copy('JSON 编辑', 'Edit JSON') }}</summary>
        <el-input v-model="roleCardJson" type="textarea" :rows="10" resize="vertical" aria-label="Character card JSON" @input="roleCardJsonDirty = true" />
        <p v-if="roleCardJsonError" class="prompt-field-error" role="alert">{{ roleCardJsonError }}</p>
        <div class="section-actions">
          <el-button size="small" plain @click="resetRoleCardJson">{{ copy('读取当前角色卡', 'Read current card') }}</el-button>
          <el-button size="small" type="primary" :disabled="!roleCardJson.trim() || !roleCardJsonDirty" @click="applyRoleCardJson(roleCardJson)">{{ copy('应用 JSON', 'Apply JSON') }}</el-button>
        </div>
      </details>
    </section>

    <section v-show="section === 'all' || section === 'world'" class="prompt-section">
      <header class="prompt-section-header">
        <h3>{{ t('promptPanel.world.title') }}</h3>
        <el-switch v-model="worldBookModel.enabled" size="small" inline-prompt :active-text="t('promptPanel.switch.on')" :inactive-text="t('promptPanel.switch.off')" />
      </header>

      <div class="world-book-options">
        <label>
          <span>{{ t('promptPanel.world.scanDepth') }}</span>
          <el-input-number v-model="worldBookModel.scanDepth" size="small" :min="1" :max="32" controls-position="right" />
        </label>
        <label>
          <span>{{ t('promptPanel.world.maxEntries') }}</span>
          <el-input-number v-model="worldBookModel.maxEntries" size="small" :min="1" :max="64" controls-position="right" />
        </label>
        <label>
          <span>{{ t('promptPanel.world.budget') }}</span>
          <el-input-number v-model="worldBookModel.budgetTokens" size="small" :min="128" :max="32000" :step="128" controls-position="right" />
        </label>
      </div>

      <div class="world-toolbar">
        <el-input v-model="worldBookSearch" size="small" :placeholder="t('promptPanel.world.searchPlaceholder')" clearable />
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
          @change="toggleFilteredWorldEntrySelection($event === true)"
        >
          {{ t('promptPanel.world.selectAllFiltered') }}
        </el-checkbox>
        <span>{{ t('promptPanel.world.selectedCount', { count: selectedWorldEntryIds.length }) }}</span>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="batchSetWorldEntriesEnabled(true)">{{ t('promptPanel.world.enableSelected') }}</el-button>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="batchSetWorldEntriesEnabled(false)">{{ t('promptPanel.world.disableSelected') }}</el-button>
        <el-button size="small" plain :disabled="selectedWorldEntryIds.length === 0" @click="exportSelectedWorldBookFile">{{ t('promptPanel.world.exportSelected') }}</el-button>
        <el-button size="small" text type="danger" :disabled="selectedWorldEntryIds.length === 0" @click="removeSelectedWorldEntries">{{ t('promptPanel.world.deleteSelected') }}</el-button>
      </div>

      <div class="world-import-row">
        <el-input
          v-model="worldBookJson"
          type="textarea"
          :rows="dense ? 3 : 4"
          resize="none"
          :placeholder="t('promptPanel.world.importPlaceholder')"
        />
        <div class="world-import-actions">
          <div class="mode-segment world-import-mode">
            <button
              type="button"
              :class="{ active: worldBookImportMode === 'replace' }"
              @click="worldBookImportMode = 'replace'"
            >
              {{ t('promptPanel.world.importModeReplace') }}
            </button>
            <button
              type="button"
              :class="{ active: worldBookImportMode === 'merge' }"
              @click="worldBookImportMode = 'merge'"
            >
              {{ t('promptPanel.world.importModeMerge') }}
            </button>
          </div>
          <input ref="worldBookFileInput" class="hidden-file-input" type="file" accept=".json,application/json" @change="importWorldBookFile">
          <el-button size="small" plain @click="openWorldBookFilePicker">{{ t('promptPanel.world.importFile') }}</el-button>
          <el-button size="small" type="primary" plain :disabled="!worldBookJson.trim()" @click="importWorldBookJson">{{ t('promptPanel.world.importJson') }}</el-button>
          <el-button size="small" plain :disabled="!worldBookModel.entries.length" @click="exportWorldBookFile">{{ t('promptPanel.world.exportFile') }}</el-button>
          <el-button size="small" text :disabled="!worldBookJson.trim()" @click="worldBookJson = ''">{{ t('promptPanel.world.clear') }}</el-button>
        </div>
      </div>
      <p v-if="worldBookJsonError" class="prompt-field-error">{{ worldBookJsonError }}</p>

      <div v-if="worldBookModel.entries.length" class="world-preview" data-testid="world-book-preview">
        <div class="world-preview-head">
          <span>{{ copy('本地近似触发预览', 'Local approximate trigger preview') }}</span>
          <span>{{ worldBookPreviewStatus }}</span>
        </div>
        <el-input
          v-model="worldBookPreviewText"
          data-testid="world-book-preview-input"
          type="textarea"
          :rows="dense ? 2 : 3"
          resize="none"
          :placeholder="t('promptPanel.world.previewPlaceholder')"
        />
        <div v-if="worldBookPreviewMatches.length" class="world-preview-list">
          <button
            v-for="match in worldBookPreviewMatches"
            :key="match.entry.id"
            type="button"
            class="world-preview-item"
            @click="focusWorldEntryFromPreview(match.entry)"
          >
            <span>{{ match.entry.title || t('promptPanel.world.untitledEntry') }}</span>
            <small>{{ match.reason }}</small>
          </button>
        </div>
        <div v-else class="world-preview-empty">{{ worldBookPreviewEmptyLabel }}</div>
      </div>

      <div class="world-entry-create">
        <el-input v-model="worldEntryDraft.title" size="small" :placeholder="t('promptPanel.world.entryTitlePlaceholder')" />
        <el-input v-model="worldEntryDraft.keys" size="small" :placeholder="t('promptPanel.world.entryKeysPlaceholder')" />
        <el-button size="small" type="primary" plain :disabled="!worldEntryDraft.title.trim() && !worldEntryDraft.content.trim()" @click="addWorldEntry">{{ t('promptPanel.world.addEntry') }}</el-button>
      </div>
      <el-input v-model="worldEntryDraft.content" class="world-entry-draft-content" type="textarea" :rows="2" resize="none" :placeholder="t('promptPanel.world.entryContentPlaceholder')" />

      <template v-if="filteredWorldEntries.length">
        <div class="world-entry-list">
          <article v-for="entry in pagedWorldEntries" :key="entry.id" class="world-entry">
            <div class="world-entry-head">
              <el-checkbox :model-value="isWorldEntrySelected(entry.id)" @change="($event) => setWorldEntrySelected(entry.id, $event === true)" />
              <el-switch v-model="entry.enabled" size="small" />
              <el-input v-model="entry.title" size="small" :placeholder="t('promptPanel.world.entryTitlePlaceholder')" />
              <el-input-number v-model="entry.priority" size="small" :min="0" :max="99" controls-position="right" />
              <el-button size="small" text type="danger" @click="removeWorldEntry(entry.id)">{{ t('promptPanel.world.deleteEntry') }}</el-button>
            </div>
            <el-input :model-value="entry.keys.join(', ')" size="small" :placeholder="t('promptPanel.world.entryKeys')" @update:model-value="(value: string) => updateWorldEntryKeys(entry.id, value)" />
            <el-input :model-value="entry.secondaryKeys.join(', ')" size="small" :placeholder="t('promptPanel.world.entrySecondaryKeys')" @update:model-value="(value: string) => updateWorldEntrySecondaryKeys(entry.id, value)" />
            <div class="world-entry-options">
              <label>
                <span>{{ t('promptPanel.world.entryOrder') }}</span>
                <el-input-number v-model="entry.insertionOrder" size="small" :min="-999" :max="999" controls-position="right" />
              </label>
              <label>
                <span>{{ t('promptPanel.world.entryProbability') }}</span>
                <el-input-number v-model="entry.probability" size="small" :min="0" :max="100" controls-position="right" />
              </label>
              <el-switch v-model="entry.constant" size="small" inline-prompt :active-text="t('promptPanel.world.entryConstant')" :inactive-text="t('promptPanel.world.entryConstant')" />
              <el-switch v-model="entry.selective" size="small" inline-prompt :active-text="t('promptPanel.world.entrySelective')" :inactive-text="t('promptPanel.world.entrySelective')" />
              <el-switch v-model="entry.caseSensitive" size="small" inline-prompt :active-text="t('promptPanel.world.entryCaseSensitive')" :inactive-text="t('promptPanel.world.entryCaseSensitive')" />
              <el-switch v-model="entry.matchWholeWords" size="small" inline-prompt :active-text="t('promptPanel.world.entryWholeWords')" :inactive-text="t('promptPanel.world.entryWholeWords')" />
            </div>
            <el-input v-model="entry.content" type="textarea" :rows="dense ? 2 : 3" resize="none" :placeholder="t('promptPanel.world.entryContent')" />
          </article>
        </div>
        <div v-if="worldBookTotalPages > 1" class="world-pager">
          <span>{{ t('promptPanel.world.pageIndicator', { page: worldBookPage, total: worldBookTotalPages }) }}</span>
          <div>
            <el-button size="small" plain :disabled="worldBookPage <= 1" @click="goWorldBookPage(-1)">{{ t('promptPanel.world.prevPage') }}</el-button>
            <el-button size="small" plain :disabled="worldBookPage >= worldBookTotalPages" @click="goWorldBookPage(1)">{{ t('promptPanel.world.nextPage') }}</el-button>
          </div>
        </div>
      </template>
      <el-empty v-else :description="worldBookModel.entries.length ? t('promptPanel.world.emptyFiltered') : t('promptPanel.world.emptyAll')" :image-size="48" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { ElEmpty } from 'element-plus'
import 'element-plus/es/components/empty/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElCheckbox, ElSwitch } from 'element-plus'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/switch/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { currentLocale, t } from '@/i18n'
import { createEmptyRoleCard, cloneRoleCard, hasRoleCardContent, parseCharacterCard, exportCharacterCard } from '@/domains/prompt/character-card'
import { defaultDailyPrompt, defaultWorkPrompt, isBuiltinDailyPrompt, isBuiltinWorkPrompt, useWorkspaceStore } from '@/stores/workspaceStore'
import type { WorkspacePromptEngineering, WorkspacePromptMode, WorkspaceRoleCard, WorkspaceWorldBook, WorkspaceWorldBookEntry } from '@/../shared/workspace'

withDefaults(defineProps<{
  showMode?: boolean
  dense?: boolean
  section?: 'all' | 'role' | 'world' | 'behavior'
}>(), {
  showMode: true,
  dense: false,
  section: 'all',
})

const workspaceStore = useWorkspaceStore()
const copy = (zh: string, en: string) => currentLocale.value === 'zh-CN' ? zh : en
let syncingPromptContext = false

const roleCardModel = reactive<WorkspaceRoleCard>(createEmptyRoleCard())
const addGreeting = () => {
  if ((roleCardModel.alternateGreetings?.length || 0) >= 20) return
  roleCardModel.alternateGreetings = [...(roleCardModel.alternateGreetings || []), '']
}
const removeGreeting = (index: number) => {
  const greetings = roleCardModel.alternateGreetings || []
  if (index < 0 || index >= greetings.length) return
  greetings.splice(index, 1)
  const selected = roleCardModel.greetingIndex ?? -1
  if (selected === index) roleCardModel.greetingIndex = -1
  else if (selected > index) roleCardModel.greetingIndex = selected - 1
}
const moveGreeting = (index: number, delta: number) => {
  const greetings = roleCardModel.alternateGreetings || []
  const target = index + delta
  if (target < 0 || target >= greetings.length || index < 0 || index >= greetings.length) return
  const selected = roleCardModel.greetingIndex ?? -1
  const text = greetings[index]!
  greetings[index] = greetings[target]!
  greetings[target] = text
  if (selected === index) roleCardModel.greetingIndex = target
  else if (selected === target) roleCardModel.greetingIndex = index
}
const roleCardJson = ref('')
const roleCardJsonError = ref('')
const roleCardJsonDirty = ref(false)
const promptEngineeringModel = reactive<WorkspacePromptEngineering>({
  workPrompt: defaultWorkPrompt(),
  dailyPrompt: defaultDailyPrompt(),
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

const promptModeOptions = computed<Array<{ label: string; value: WorkspacePromptMode }>>(() => [
  { label: t('promptPanel.mode.auto'), value: 'auto' },
  { label: t('promptPanel.mode.work'), value: 'work' },
  { label: t('promptPanel.mode.daily'), value: 'daily' },
])

const worldBookStateFilterOptions = computed<Array<{ label: string; value: 'all' | 'enabled' | 'disabled' }>>(() => [
  { label: t('promptPanel.world.filterAll'), value: 'all' },
  { label: t('promptPanel.world.filterEnabled'), value: 'enabled' },
  { label: t('promptPanel.world.filterDisabled'), value: 'disabled' },
])

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
      reason: t('promptPanel.world.matchConstant'),
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
      a.entry.insertionOrder - b.entry.insertionOrder ||
      b.entry.priority - a.entry.priority ||
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
  if (!worldBookModel.enabled) return t('promptPanel.world.previewDisabled')
  const usedCharacters = worldBookPreviewMatches.value.reduce((total, match) => total + match.contentCharacters, 0)
  return t('promptPanel.world.previewStatus', {
    count: worldBookPreviewMatches.value.length,
    chars: usedCharacters,
  })
})

const worldBookPreviewEmptyLabel = computed(() => {
  if (!worldBookModel.enabled) return t('promptPanel.world.previewWorldDisabled')
  return worldBookPreviewText.value.trim()
    ? t('promptPanel.world.previewNoMatch')
    : t('promptPanel.world.previewWaiting')
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

const roleCardToJson = (card: WorkspaceRoleCard) => hasRoleCardContent(card) ? JSON.stringify(exportCharacterCard(card), null, 2) : ''
const resetRoleCardJson = () => {
  roleCardJson.value = roleCardToJson(roleCardModel)
  roleCardJsonError.value = ''
  roleCardJsonDirty.value = false
}

const clonePromptEngineering = (source?: Partial<WorkspacePromptEngineering>): WorkspacePromptEngineering => ({
  workPrompt: source?.workPrompt?.trim() && !isBuiltinWorkPrompt(source.workPrompt) ? source.workPrompt : defaultWorkPrompt(),
  dailyPrompt: source?.dailyPrompt?.trim() && !isBuiltinDailyPrompt(source.dailyPrompt) ? source.dailyPrompt : defaultDailyPrompt(),
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
  resetRoleCardJson()
  const worldBook = cloneWorldBook(workspaceStore.activeWorkspace.context.worldBook)
  worldBookModel.enabled = worldBook.enabled
  worldBookModel.scanDepth = worldBook.scanDepth
  worldBookModel.maxEntries = worldBook.maxEntries
  worldBookModel.budgetTokens = worldBook.budgetTokens
  worldBookModel.entries = worldBook.entries
  worldBookJson.value = ''
  worldBookJsonError.value = ''
  void nextTick(() => { syncingPromptContext = false })
}

const persistPromptContext = (patch: Parameters<typeof workspaceStore.updateWorkspaceContext>[1]) => {
  if (!syncingPromptContext) workspaceStore.updateWorkspaceContext(activeWorkspaceId.value, patch)
}

const resetBasePrompts = () => {
  promptEngineeringModel.workPrompt = defaultWorkPrompt()
  promptEngineeringModel.dailyPrompt = defaultDailyPrompt()
}

const setRoleCardJsonText = (value: string) => {
  roleCardJson.value = value
  roleCardJsonDirty.value = true
  applyRoleCardJson(value)
}

const openRoleCardFilePicker = () => {
  roleCardFileInput.value?.click()
}

const importRoleCardFile = async (event: Event) => {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  const workspaceId = activeWorkspaceId.value
  try {
    const text = await file.text()
    if (workspaceId !== activeWorkspaceId.value) return
    setRoleCardJsonText(text)
  } catch {
    if (workspaceId === activeWorkspaceId.value) roleCardJsonError.value = t('promptPanel.common.readJsonFailed')
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
  if (!hasRoleCardContent(roleCardModel)) return
  const original = roleCardModel.sourceCard
  const originalData = isRecord(original?.data) ? original.data : original
  const includeWorldBook = worldBookModel.enabled || worldBookModel.entries.length > 0 || Boolean(originalData?.character_book)
  exportJsonFile(exportCharacterCard(roleCardModel, includeWorldBook ? cloneWorldBook(worldBookModel) : undefined), `${activeWorkspaceId.value || 'workspace'}-role-card.json`)
}

const addWorldEntry = () => {
  const title = worldEntryDraft.title.trim()
  const content = worldEntryDraft.content.trim()
  if (!title && !content) return
  worldBookModel.enabled = true
  worldBookModel.entries.unshift({
    id: createWorldEntryId(),
    title: title || t('promptPanel.world.untitledEntry'),
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
  const local = isRecord(extensions.yuizaki) ? extensions.yuizaki : {}
  const content = readString(raw, ['content', 'entry', 'text', 'value', 'prompt']).trim()
  if (!content) return null
  const disabled = readBoolean(raw, ['disable', 'disabled'], false)
  const order = readNumber(raw, ['insertionOrder', 'insertion_order', 'order'], index)
  const secondaryKeys = readStringList(raw, ['secondaryKeys', 'secondary_keys', 'keysecondary', 'secondary', 'secondaryKeywords', 'secondary_keywords'])
  const id = readIdentifier(raw, ['id', 'uid']) || readIdentifier(local, ['id'])
  return {
    id: id || createWorldEntryId(),
    title: readString(raw, ['title', 'comment', 'name', 'memo', 'displayName']) || id || t('promptPanel.world.entryFallbackTitle', { index: index + 1 }),
    keys: readStringList(raw, ['keys', 'key', 'primaryKeys', 'primary_keys', 'keywords', 'triggers']),
    secondaryKeys,
    content,
    enabled: raw.enabled === false ? false : !disabled,
    priority: readNumber(raw, ['priority'], 0),
    insertionOrder: order,
    constant: readBoolean(raw, ['constant'], false),
    selective: readBoolean(raw, ['selective'], secondaryKeys.length > 0),
    caseSensitive: readBoolean(raw, ['caseSensitive', 'case_sensitive'], false) || readBoolean(extensions, ['case_sensitive'], false),
    matchWholeWords: readBoolean(raw, ['matchWholeWords', 'match_whole_words'], false) || readBoolean(extensions, ['match_whole_words'], false) || readBoolean(local, ['matchWholeWords'], false),
    probability: readBoolean(raw, ['useProbability', 'use_probability'], true) === false
      ? 100
      : Math.max(0, Math.min(100, readNumber(raw, ['probability'], readNumber(local, ['probability'], 100)))),
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
  const extensions = isRecord(book.extensions) ? book.extensions : {}
  const local = isRecord(extensions.yuizaki) ? extensions.yuizaki : {}
  worldBookModel.enabled = readBoolean(book, ['enabled'], readBoolean(local, ['enabled'], true))
  worldBookModel.scanDepth = Math.max(1, Math.min(32, Math.round(readNumber(book, ['scanDepth', 'scan_depth', 'depth'], worldBookModel.scanDepth))))
  worldBookModel.maxEntries = Math.max(1, Math.min(64, Math.round(readNumber(book, ['maxEntries', 'max_entries'], readNumber(local, ['maxEntries'], Math.max(worldBookModel.maxEntries, entries.length))))))
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
      worldBookJsonError.value = t('promptPanel.world.invalidShape')
      return
    }
    if (!applyImportedWorldBook(book, worldBookImportMode.value)) {
      worldBookJsonError.value = t('promptPanel.world.noImportableEntries')
      return
    }
    worldBookJsonError.value = ''
    worldBookJson.value = ''
  } catch {
    worldBookJsonError.value = t('promptPanel.common.invalidJson')
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
  const workspaceId = activeWorkspaceId.value
  try {
    const text = await file.text()
    if (workspaceId !== activeWorkspaceId.value) return
    importWorldBookFromText(text)
  } catch {
    if (workspaceId === activeWorkspaceId.value) worldBookJsonError.value = t('promptPanel.common.readJsonFailed')
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
      roleCardJsonError.value = t('promptPanel.roleCard.invalidShape')
      return
    }
    roleCardJsonError.value = ''
    Object.assign(roleCardModel, createEmptyRoleCard(roleCardModel.enabled), parseCharacterCard(parsed, roleCardModel.enabled))
    const embeddedWorldBook = resolveEmbeddedWorldBook(parsed)
    if (embeddedWorldBook) {
      applyImportedWorldBook(embeddedWorldBook, worldBookModel.entries.length ? 'merge' : 'replace')
    }
    resetRoleCardJson()
  } catch {
    roleCardJsonError.value = t('promptPanel.roleCard.invalidJson')
  }
}

syncPromptModelsFromWorkspace()
watch(activeWorkspaceId, syncPromptModelsFromWorkspace, { flush: 'sync' })
watch([worldBookSearch, worldBookStateFilter], () => {
  worldBookPage.value = 1
})
watch(() => filteredWorldEntries.value.length, () => {
  worldBookPage.value = Math.max(1, Math.min(worldBookPage.value, worldBookTotalPages.value))
  const validIds = new Set(worldBookModel.entries.map((entry) => entry.id))
  selectedWorldEntryIds.value = selectedWorldEntryIds.value.filter((id) => validIds.has(id))
})
watch(promptEngineeringModel, () => persistPromptContext({ promptEngineering: clonePromptEngineering(promptEngineeringModel) }), { deep: true })
watch(roleCardModel, () => {
  persistPromptContext({ roleCard: cloneRoleCard(roleCardModel) })
  if (!syncingPromptContext && !roleCardJsonDirty.value) resetRoleCardJson()
}, { deep: true })
watch(worldBookModel, () => persistPromptContext({ worldBook: cloneWorldBook(worldBookModel) }), { deep: true })
</script>

<style scoped>
.alternate-greetings { border-top: 1px solid var(--yui-border); padding-top: 14px; }
.alternate-greetings > summary { cursor: pointer; font-size: 13px; font-weight: 650; color: var(--yui-text); }
.alternate-greetings > summary span { color: var(--yui-muted); font-weight: 400; margin-left: 6px; }
.greeting-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.alternate-greetings > .greeting-actions { margin: 14px 0; }
.greeting-actions :deep(.el-button + .el-button) { margin-left: 0; }
.greeting-entry { padding: 14px 0; border-top: 1px solid var(--yui-border); }
.greeting-entry > header { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 13px; }

.role-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px 22px; }
.role-field-wide { grid-column: 1 / -1; }
.role-fields :deep(.el-form-item) { margin-bottom: 0; min-width: 0; }
.role-json-editor { border-top: 1px solid var(--yui-border); padding-top: 12px; }
.role-json-editor summary { cursor: pointer; color: var(--yui-text); font-size: 13px; padding: 4px 0 12px; }
.role-json-editor .section-actions { margin-top: 10px; justify-content: flex-end; }
@media (max-width: 1060px) { .role-fields { grid-template-columns: minmax(0, 1fr); } }

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

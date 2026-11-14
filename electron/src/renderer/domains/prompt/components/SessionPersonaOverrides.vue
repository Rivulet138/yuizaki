<template>
  <details class="session-persona">
    <summary>{{ copy('当前会话设定', 'Session settings') }}<span>{{ selectedSession?.title || copy('选择会话', 'Select a session') }}</span></summary>
    <div class="session-persona-body">
      <label class="session-picker">
        <span>{{ copy('会话', 'Session') }}</span>
        <select :value="selectedSession?.id || ''" :disabled="loading || sessionStore.loading" :aria-label="copy('选择会话', 'Select a session')" @change="selectSession">
          <option value="" disabled>{{ copy('选择会话', 'Select a session') }}</option>
          <option v-for="session in workspaceSessions" :key="session.id" :value="session.id">{{ session.title }}</option>
        </select>
        <el-button size="small" plain :loading="loading" @click="loadSessions">{{ copy('刷新会话', 'Refresh sessions') }}</el-button>
      </label>
      <template v-if="draft && selectedSession">
        <div v-for="field in fields" :key="field.key" class="session-field">
          <label><input type="checkbox" :checked="hasOverride(field.key)" :disabled="saving" @change="toggleOverride(field.key, $event)" />{{ field.label }}</label>
          <el-input v-if="hasOverride(field.key)" v-model="draft.value[field.key]" type="textarea" :rows="4" :maxlength="1600" show-word-limit resize="vertical" :aria-label="field.label" />
        </div>
        <p v-if="conflict" class="session-error" role="status">{{ copy('会话设定已更新，保留了你的草稿。', 'Session settings changed; your draft is preserved.') }}</p>
        <div class="session-actions">
          <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="save">{{ copy('保存本会话', 'Save session') }}</el-button>
          <el-button size="small" plain :disabled="saving || (!dirty && !hasSavedOverrides)" @click="restoreInheritance">{{ copy('恢复继承', 'Restore inheritance') }}</el-button>
          <el-button v-if="dirty" size="small" plain :disabled="saving" @click="discardDraft">{{ copy('放弃草稿', 'Discard draft') }}</el-button>
        </div>
      </template>
      <p v-if="error" class="session-error" role="alert">{{ error }}</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElButton, ElInput } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/input/style/css'
import { currentLocale } from '@/i18n'
import { describeFailure } from '@/shared/errors/describe-error'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useSessionStore, type SessionPersonaOverrides } from '@/stores/sessionStore'

const workspaceStore = useWorkspaceStore()
const sessionStore = useSessionStore()
const copy = (zh: string, en: string) => currentLocale.value === 'zh-CN' ? zh : en
const fields = computed(() => [
  { key: 'scenario' as const, label: copy('覆盖本会话场景', 'Override session scenario') },
  { key: 'exampleDialogue' as const, label: copy('覆盖本会话对话示例', 'Override session examples') },
])
type Field = keyof SessionPersonaOverrides
interface Draft { value: SessionPersonaOverrides; base: string }
const clone = (value?: SessionPersonaOverrides | null): SessionPersonaOverrides => ({
  ...(typeof value?.scenario === 'string' ? { scenario: value.scenario } : {}),
  ...(typeof value?.exampleDialogue === 'string' ? { exampleDialogue: value.exampleDialogue } : {}),
})
const serialize = (value?: SessionPersonaOverrides | null) => JSON.stringify(clone(value))
const drafts = reactive<Record<string, Draft>>({})
const pending = reactive<Record<string, boolean>>({})
const errors = reactive<Record<string, string>>({})
const loading = ref(false)
const loadError = ref('')
let disposed = false
let loadEpoch = 0
const workspaceId = computed(() => workspaceStore.activeWorkspace.id)
const workspaceSessions = computed(() => sessionStore.sessions.filter(session => session.workspace_id === workspaceId.value))
const selectedSession = computed(() => workspaceSessions.value.find(session => session.id === sessionStore.activeSessionId))
const key = computed(() => selectedSession.value ? JSON.stringify([workspaceId.value, selectedSession.value.id]) : '')
const draft = computed(() => drafts[key.value])
const saving = computed(() => Boolean(pending[key.value]))
const error = computed(() => errors[key.value] || loadError.value)
const dirty = computed(() => Boolean(draft.value && serialize(draft.value.value) !== draft.value.base))
const conflict = computed(() => Boolean(dirty.value && selectedSession.value && draft.value?.base !== serialize(selectedSession.value.persona_overrides)))
const hasSavedOverrides = computed(() => Object.keys(clone(selectedSession.value?.persona_overrides)).length > 0)
watch(() => [key.value, serialize(selectedSession.value?.persona_overrides)] as const, ([id, remote]) => {
  if (!id) return
  const current = drafts[id]
  if (!current || serialize(current.value) === current.base) drafts[id] = { value: JSON.parse(remote), base: remote }
}, { immediate: true, flush: 'sync' })
const hasOverride = (field: Field) => Boolean(draft.value && Object.hasOwn(draft.value.value, field))
const toggleOverride = (field: Field, event: Event) => {
  if (!draft.value || saving.value) return
  if ((event.target as HTMLInputElement).checked) {
    draft.value.value[field] = workspaceStore.activeWorkspace.context.roleCard[field] || ''
  } else delete draft.value.value[field]
}
const selectSession = (event: Event) => {
  const id = (event.target as HTMLSelectElement).value
  if (workspaceSessions.value.some(session => session.id === id)) sessionStore.setActiveSession(id)
}
const discardDraft = () => {
  if (!selectedSession.value || saving.value) return
  const remote = serialize(selectedSession.value.persona_overrides)
  drafts[key.value] = { value: JSON.parse(remote), base: remote }
  errors[key.value] = ''
}
const persist = async (value: SessionPersonaOverrides | null) => {
  const session = selectedSession.value
  const id = key.value
  if (!session || !drafts[id] || pending[id]) return
  const targetWorkspaceId = workspaceId.value
  const sentDraft = serialize(drafts[id].value)
  const payload = value === null ? null : clone(value)
  pending[id] = true
  errors[id] = ''
  try {
    const saved = await sessionStore.updateSession(session.id, { persona_overrides: payload }, targetWorkspaceId)
    if (disposed) return
    const remote = serialize(saved.persona_overrides)
    // A late response belongs to the captured draft, never the newly selected session.
    if (serialize(drafts[id].value) === sentDraft) drafts[id] = { value: JSON.parse(remote), base: remote }
    else drafts[id].base = remote
  } catch (failure) {
    if (!disposed) errors[id] = describeFailure(failure, copy('会话设定保存失败，请重试。', 'Could not save session settings. Try again.'))
  } finally { pending[id] = false }
}
const save = () => draft.value && dirty.value ? persist(draft.value.value) : Promise.resolve()
const restoreInheritance = () => persist(null)
const loadSessions = async () => {
  const epoch = ++loadEpoch
  loading.value = true
  loadError.value = ''
  try { await sessionStore.loadSessions() }
  catch (failure) { if (!disposed && epoch === loadEpoch) loadError.value = describeFailure(failure, copy('会话加载失败，请重试。', 'Could not load sessions. Try again.')) }
  finally { if (!disposed && epoch === loadEpoch) loading.value = false }
}
watch(workspaceId, () => { void loadSessions() })
onMounted(() => { void loadSessions() })
onBeforeUnmount(() => { disposed = true; loadEpoch += 1 })
</script>

<style scoped>
.session-persona { border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-raised); padding: 16px; min-width: 0; }
summary { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; cursor: pointer; color: var(--yui-text); font-size: 13px; font-weight: 650; }
summary > span { color: var(--yui-muted); font-size: 12px; font-weight: 400; overflow-wrap: anywhere; }
.session-persona-body { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }
.session-picker { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--yui-muted); }
select { min-width: 0; flex: 1; max-width: 100%; font: inherit; color: var(--yui-text); border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control, 8px); background: var(--yui-surface-raised); padding: 7px; }
.session-field { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.session-field > label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--yui-text); }
input[type=checkbox] { accent-color: var(--yui-accent); }
.session-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.session-actions :deep(.el-button + .el-button) { margin-left: 0; }
.session-error { margin: 0; color: var(--el-color-danger); font-size: 13px; overflow-wrap: anywhere; }
summary:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: 3px; }
</style>

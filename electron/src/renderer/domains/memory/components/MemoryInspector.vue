<template>
  <aside class="inspector" :aria-label="t('memoryView.inspectorAria')" data-testid="memory-inspector">
    <template v-if="doc">
       <header class="inspector-header"><div class="inspector-title"><span class="eyebrow">{{ t('memoryView.inspectorAria') }}</span><strong>{{ doc.type || t('memoryView.memoryFallback') }}</strong><p>{{ docScopeLabel(doc) }} · {{ docSourceLabel(doc) }} · {{ updatedLabel(doc) }}</p><small v-if="doc.memory_role" class="role-label">{{ memoryRoleLabel(doc.memory_role) }}</small></div><el-tag size="small" :type="stateTone">{{ stateLabel }}</el-tag></header>
      <label class="content-field"><span>{{ t('memoryView.inspectorContent') }}</span><el-input :model-value="draft.text" data-testid="memory-inspector-text" type="textarea" :rows="5" resize="none" @update:model-value="updateDraft('text', String($event))" /></label>
       <div class="fact-grid" :aria-label="t('memoryView.inspectorSummaryAria')"><div><span>{{ t('memoryView.fieldLayer') }}</span><strong>{{ layerLabel(draft.layer) }}</strong></div><div><span>{{ t('memoryView.reliability') }}</span><strong>{{ qualityPercent(doc) }}</strong></div></div>
      <div class="actions"><div class="save-state" :class="{ dirty }" role="status">{{ dirty ? t('memoryView.inspectorUnsaved') : t('memoryView.saved') }}</div><el-button data-testid="memory-inspector-save" size="small" type="primary" :loading="saving" :disabled="!dirty || !draft.text.trim()" @click="emit('save')">{{ t('memoryView.inspectorSave') }}</el-button><el-button size="small" plain :disabled="!dirty" @click="emit('reset')">{{ t('memoryView.inspectorReset') }}</el-button><el-button data-testid="memory-inspector-forget" size="small" type="warning" plain :loading="forgetting" :disabled="forgetting" @click="emit('forget', doc.id)">{{ t('memoryView.paused') }}</el-button></div>
      <details class="edit-details"><summary>{{ t('memoryView.inspectorEditTitle') }}</summary><div class="field-grid"><label><span>{{ t('memoryView.fieldType') }}</span><el-input :model-value="draft.type" size="small" @update:model-value="updateDraft('type', String($event))" /></label><label><span>{{ t('memoryView.fieldLayer') }}</span><el-select :model-value="draft.layer" size="small" @update:model-value="updateDraft('layer', String($event))"><el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" /></el-select></label><label><span>{{ t('memoryView.fieldSource') }}</span><el-select :model-value="draft.source" size="small" @update:model-value="updateDraft('source', String($event))"><el-option v-for="option in sourceOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></label></div><div class="time-grid"><label><span>{{ t('memoryView.fieldValidFrom') }}</span><el-input :model-value="draft.validFrom" data-testid="memory-valid-from" type="datetime-local" size="small" @update:model-value="updateDraft('validFrom', String($event))" /></label><label><span>{{ t('memoryView.fieldValidTo') }}</span><el-input :model-value="draft.validTo" data-testid="memory-valid-to" type="datetime-local" size="small" @update:model-value="updateDraft('validTo', String($event))" /></label><label><span>{{ t('memoryView.fieldExpiresAt') }}</span><el-input :model-value="draft.expiresAt" data-testid="memory-expires-at" type="datetime-local" size="small" @update:model-value="updateDraft('expiresAt', String($event))" /></label></div><div class="slider-grid"><label><span>{{ t('memoryView.fieldImportance', { value: scorePercent(draft.importance) }) }}</span><el-slider :model-value="draft.importance" :min="0" :max="1" :step="0.05" @update:model-value="updateDraft('importance', Number($event))" /></label><label><span data-testid="memory-inspector-confidence">{{ t('memoryView.fieldConfidence', { value: scorePercent(draft.confidence) }) }}</span><el-slider :model-value="draft.confidence" :min="0" :max="1" :step="0.05" @update:model-value="updateDraft('confidence', Number($event))" /></label></div></details>
      <details v-if="evidenceIds.length"><summary>{{ t('memoryView.inspectorEvidenceTitle', { count: evidenceIds.length }) }}</summary><div class="evidence-list" data-testid="memory-inspector-evidence"><span v-for="id in evidenceIds" :key="id">{{ id }}</span></div></details>
      <details><summary>{{ t('memoryView.inspectorMore') }}</summary><div class="layer-actions"><span class="detail-label">{{ t('memoryView.moveToLayer') }}</span><button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="doc.layer === layer.value" @click="emit('move-layer', { doc, layer: layer.value })">{{ layer.label }}</button></div><div class="secondary-actions"><el-button size="small" link type="primary" @click="emit('edit', doc)">{{ t('memoryView.editAllFields') }}</el-button><el-button size="small" link @click="emit('boost', doc)">{{ t('memoryView.boostImportance') }}</el-button></div></details>
      <details><summary>{{ t('memoryView.inspectorDiagnostics') }}</summary><div class="diagnostic-groups"><details><summary>{{ t('memoryView.technicalInfo') }}</summary><pre>{{ metadataPreview(doc) }}</pre></details><details><summary>{{ t('memoryView.timelineTitle') }}<template v-if="operations.length">（{{ operations.length }}）</template></summary><div v-if="operationsLoading" class="operation-status" role="status">{{ t('memoryView.operationsLoading') }}</div><div v-else-if="operationsError" class="operation-status operation-error" role="alert">{{ t('memoryView.operationsError', { error: operationsError }) }}</div><div v-else-if="!operations.length" class="operation-status">{{ t('memoryView.operationsEmpty') }}</div><div v-else class="operations"><article v-for="item in operations" :key="item.operation_id"><div><strong>{{ operationLabel(item.operation) }}</strong><span>{{ operationTime(item.at) }}</span></div><p v-if="item.reason">{{ item.reason }}</p><small v-if="item.before_revision || item.after_revision">{{ t('memoryView.versionDiff', { before: item.before_revision ?? '-', after: item.after_revision ?? '-' }) }}</small></article></div></details><details v-if="!operationsLoading && !operations.length && auditEntries(doc).length"><summary>{{ t('memoryView.auditCompatTitle') }}</summary><div class="audit"><div v-for="(entry, index) in auditEntries(doc)" :key="index"><strong>{{ auditActionLabel(entry.action) }}</strong><span>{{ auditEntrySummary(entry) }}</span></div></div></details><details v-if="versionHistory.length"><summary>{{ t('memoryView.versionHistoryTitle', { count: versionHistory.length }) }}</summary><div class="versions"><article v-for="entry in versionHistory" :key="entry.revision"><div><strong>{{ t('memoryView.versionLabel', { revision: entry.revision }) }}</strong><span>{{ versionTimestamp(entry) }}</span></div><p>{{ entry.text || t('memoryView.versionNoSnapshot') }}</p><el-button :data-testid="`memory-rollback-${entry.revision}`" size="small" plain :loading="rollingBackRevision === entry.revision" :disabled="rollingBackRevision !== null" @click="rollback(entry.revision)">{{ t('memoryView.versionRestore') }}</el-button></article></div></details></div></details>
      <details class="danger-zone"><summary>{{ t('memoryView.dangerZoneTitle') }}</summary><el-button data-testid="memory-inspector-delete" size="small" type="danger" plain :loading="removing" :disabled="removing" @click="emit('remove', doc.id)">{{ t('memoryView.deleteForever') }}</el-button></details>
    </template>
    <el-empty v-else :description="t('memoryView.inspectorEmpty')" :image-size="56" />
  </aside>
</template>

<script setup lang="ts">
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/slider/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { computed, inject, ref } from 'vue'
import { ElButton, ElEmpty, ElInput, ElMessage, ElSelect, ElOption, ElSlider, ElTag } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { memoryInspectorActionsKey } from './memory-panel-types'
import { t } from '@/i18n'
import type { MemoryOperation } from '@/api/clients/memory-client'
import type { MemoryDoc, MemoryInspectorDraft, MemoryLayer, MemoryOption, MemoryVersionSnapshot } from './memory-panel-types'
import { describeFailure } from '@/shared/errors/describe-error'

const props = defineProps<{ doc: MemoryDoc | null; draft: MemoryInspectorDraft; layers: MemoryLayer[]; sourceOptions: MemoryOption[]; dirty: boolean; saving: boolean; forgetting: boolean; removing: boolean; docScopeLabel:(doc:MemoryDoc)=>string; docSourceLabel:(doc:MemoryDoc)=>string; qualityPercent:(doc:MemoryDoc)=>string; metadataPreview:(doc:MemoryDoc)=>string; auditEntries:(doc:MemoryDoc)=>Array<Record<string,unknown>>; auditActionLabel:(value:unknown)=>string; auditEntrySummary:(entry:Record<string,unknown>)=>string; operations: MemoryOperation[]; operationsLoading: boolean; operationsError?: string | null }>()
const emit = defineEmits<{ save:[]; reset:[]; edit:[doc:MemoryDoc]; boost:[doc:MemoryDoc]; forget:[id:string]; remove:[id:string]; 'move-layer':[payload:{doc:MemoryDoc;layer:string}]; 'update-draft':[value:Partial<MemoryInspectorDraft>] }>()
const inspectorActions = inject(memoryInspectorActionsKey, null)
const rollingBackRevision = ref<number | null>(null)
const stateLabels = computed<Record<string, string>>(() => ({
  active: t('memoryView.availableForChat'),
  forgotten: t('memoryView.paused'),
  expired: t('memoryView.stateExpired'),
  scheduled: t('memoryView.stateScheduled'),
  superseded: t('memoryView.stateSupersededAlt'),
  rejected: t('memoryView.stateRejected'),
  invalid: t('memoryView.needsReview'),
}))
const stateLabel = computed(() => stateLabels.value[String(props.doc?.state || 'active')] || t('memoryView.stateFallback'))
const stateTone = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  const state = String(props.doc?.state || 'active')
  if (state === 'active') return 'success'
  if (state === 'forgotten' || state === 'expired' || state === 'scheduled') return 'warning'
  if (state === 'invalid' || state === 'rejected') return 'danger'
  return 'info'
})

const updateDraft = <K extends keyof MemoryInspectorDraft>(key: K, value: MemoryInspectorDraft[K]) => emit('update-draft', { [key]: value })
const scorePercent = (value: number) => `${Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100)}%`
const versionHistory = computed<MemoryVersionSnapshot[]>(() => {
  const raw = props.doc?.metadata?.version_history
  if (!Array.isArray(raw)) return []
  return raw
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object')
    .map(entry => ({
      revision: Number(entry.revision),
      text: typeof entry.text === 'string' ? entry.text : undefined,
      metadata: entry.metadata && typeof entry.metadata === 'object' ? entry.metadata as Record<string, unknown> : undefined,
    }))
    .filter(entry => Number.isInteger(entry.revision) && entry.revision >= 1)
    .sort((left, right) => right.revision - left.revision)
})
const versionTimestamp = (entry: MemoryVersionSnapshot) => {
  const value = entry.metadata?.updated_at ?? entry.metadata?.created_at
  if (typeof value !== 'string') return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : ''
}
const evidenceIds = computed(() => {
  const metadata = props.doc?.metadata ?? {}
  const ids = new Set<string>()
  const sourceIds = metadata.source_ids
  if (Array.isArray(sourceIds)) sourceIds.forEach(value => { if (typeof value === 'string' && value.trim()) ids.add(value) })
  const evidence = metadata.evidence
  if (Array.isArray(evidence)) evidence.forEach(value => {
    if (typeof value === 'string' && value.trim()) ids.add(value)
    else if (value && typeof value === 'object' && typeof (value as Record<string, unknown>).id === 'string') ids.add(String((value as Record<string, unknown>).id))
  })
  return [...ids]
})
const operationLabels = computed<Record<string, string>>(() => ({
  create: t('memoryView.operationCreate'),
  update: t('memoryView.operationUpdate'),
  correction: t('memoryView.operationCorrection'),
  review: t('memoryView.operationReview'),
  forget: t('memoryView.paused'),
  restore: t('memoryView.restore'),
  rollback: t('memoryView.operationRollback'),
  delete: t('memoryView.deleteForever'),
  feedback: t('memoryView.operationFeedback'),
  maintenance: t('memoryView.operationMaintenance'),
}))
const operationLabel = (value: string) => operationLabels.value[value] || value
const memoryRoleLabels = computed<Record<string, string>>(() => ({
  user_fact: t('memoryView.roleUserFact'),
  relationship_event: t('memoryView.roleRelationshipEvent'),
  task_experience: t('memoryView.roleTaskExperience'),
  failure_reflection: t('memoryView.roleFailureReflection'),
  reusable_skill: t('memoryView.roleReusableSkill'),
  tool_permission: t('memoryView.roleToolPermission'),
}))
 const memoryRoleLabel = (value: string) => memoryRoleLabels.value[value] || value
 const layerLabel = (value?: string) => props.layers.find(layer => layer.value === value)?.label || t('memoryView.uncategorized')
const operationTime = (value: string) => {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : value
}
const updatedLabel = (doc: MemoryDoc) => {
  const value = doc.updated_at || (typeof doc.metadata?.updated_at === 'string' ? doc.metadata.updated_at : doc.metadata?.timestamp)
  if (typeof value !== 'string' || !value.trim()) return t('memoryView.updatedUnknown')
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? t('memoryView.updatedAt', { date: date.toLocaleDateString() }) : t('memoryView.updatedUnknown')
}
const rollback = async (revision: number) => {
  if (!props.doc || !inspectorActions || rollingBackRevision.value !== null) return
  rollingBackRevision.value = revision
  try {
    await inspectorActions.rollback(props.doc, revision)
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryView.rollbackFailed')))
  } finally {
    rollingBackRevision.value = null
  }
}
</script>

<style scoped>
.inspector { container-type: inline-size; display: flex; min-width: 0; flex-direction: column; gap: 14px; padding: 16px 18px; background: var(--yui-surface); }
.inspector-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--yui-border); }
.inspector-title { display: grid; min-width: 0; gap: 4px; }
.inspector-title .eyebrow { color: var(--yui-muted); font-size: 10px; letter-spacing: .04em; }
.inspector-title strong { color: var(--yui-text); font-size: 17px; line-height: 1.3; overflow-wrap: anywhere; }
.inspector-title p { margin: 0; color: var(--yui-muted); font-size: 11px; line-height: 1.45; }
.inspector-title small { font-size: 11px; }
.inspector-help { color: var(--yui-muted); line-height: 1.45; }
.content-field, .field-grid label, .time-grid label, .slider-grid label { display: grid; min-width: 0; gap: 6px; color: var(--yui-muted); font-size: 12px; }
.content-field > span, .field-grid label > span, .time-grid label > span, .slider-grid label > span { color: var(--yui-muted); font-size: 11px; }
.content-field :deep(.el-textarea__inner) { min-height: 112px !important; color: var(--yui-text); line-height: 1.6; }
.fact-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.fact-grid div { display: grid; min-width: 0; gap: 3px; padding: 9px 10px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); background: var(--yui-surface-muted); }
.fact-grid span { color: var(--yui-muted); font-size: 10px; }
.fact-grid strong { color: var(--yui-text); font-size: 13px; overflow-wrap: anywhere; }
.actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; padding: 10px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-muted); }
.save-state { flex: 1 1 100px; color: var(--yui-muted); font-size: 11px; }
.save-state.dirty { color: var(--yui-warning-text, #a16207); font-weight: 600; }
details { border-top: 1px solid var(--yui-border); padding-top: 11px; }
details summary { color: var(--yui-muted); cursor: pointer; font-size: 12px; }
.edit-details[open] summary { margin-bottom: 12px; color: var(--yui-text); font-weight: 600; }
.details-help { margin: 0 0 10px; color: var(--yui-muted); font-size: 10px; line-height: 1.45; }
.field-grid, .time-grid, .slider-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.time-grid, .slider-grid { margin-top: 12px; }
.slider-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.layer-actions, .secondary-actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 10px; }
.layer-actions button { padding: 5px 9px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); background: transparent; color: var(--yui-muted); cursor: pointer; font-size: 11px; }
.layer-actions button[aria-pressed="true"] { border-color: var(--yui-accent); background: var(--yui-accent-soft); color: var(--yui-text); }
.detail-label { color: var(--yui-muted); font-size: 11px; }
.diagnostic-groups { display: grid; gap: 10px; margin-top: 10px; }
.diagnostic-groups details { padding: 9px 10px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); background: var(--yui-surface-muted); }
.diagnostic-groups details:first-child { border-top: 1px solid var(--yui-border); }
pre { max-height: 220px; margin: 9px 0 0; padding: 9px; overflow: auto; border-radius: var(--yui-radius-control); background: var(--yui-surface); color: var(--yui-muted); font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.evidence-list { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 9px; }
.evidence-list span { padding: 4px 7px; border-radius: var(--yui-radius-control); background: var(--yui-surface-muted); color: var(--yui-muted); font-size: 10px; overflow-wrap: anywhere; }
.versions { display: grid; gap: 8px; margin-top: 9px; }
.versions article { display: grid; grid-template-columns: 1fr auto; gap: 4px 10px; padding: 9px; border-radius: var(--yui-radius-control); background: var(--yui-surface); }
.versions article > div { display: flex; justify-content: space-between; gap: 8px; }
.versions article span { color: var(--yui-muted); font-size: 10px; }
.versions article p { grid-column: 1 / -1; margin: 0; color: var(--yui-text); font-size: 11px; line-height: 1.45; }
.versions article :deep(.el-button) { grid-column: 2; grid-row: 1 / span 2; align-self: center; }
.audit { display: grid; gap: 7px; margin-top: 9px; }
.audit div { display: flex; justify-content: space-between; gap: 8px; color: var(--yui-muted); font-size: 10px; }
.audit strong { color: var(--yui-text); }
.danger-zone { border-color: color-mix(in srgb, var(--yui-danger) 35%, var(--yui-border)); }
.danger-zone[open] { padding: 10px; border: 1px solid color-mix(in srgb, var(--yui-danger) 35%, var(--yui-border)); border-radius: var(--yui-radius-control); }
.operation-status { margin-top: 8px; color: var(--yui-muted); font-size: 11px; }
.operations { display: grid; gap: 8px; margin-top: 8px; }
.operations article { display: grid; gap: 3px; padding: 9px; background: var(--yui-surface-muted); border-radius: var(--yui-radius-control); }
.operations article div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.operations article span, .operations article small { color: var(--yui-muted); font-size: 10px; }
.operations article p { margin: 0; color: var(--yui-text); font-size: 11px; overflow-wrap: anywhere; }
.role-label { color: var(--yui-accent) !important; }
.operation-error { color: var(--yui-danger); }
@container (max-width: 520px){.field-grid,.time-grid,.slider-grid{grid-template-columns:1fr;}}
@media(max-width:620px){.inspector{padding:14px 12px}.fact-grid{grid-template-columns:1fr 1fr}.field-grid,.time-grid,.slider-grid{grid-template-columns:1fr}.versions article{grid-template-columns:1fr}.versions article :deep(.el-button){grid-column:1;grid-row:auto;justify-self:start}.actions :deep(.el-button){flex:1 1 auto}}
</style>

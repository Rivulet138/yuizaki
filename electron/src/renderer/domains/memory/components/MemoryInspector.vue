<template>
  <aside class="inspector" aria-label="记忆详情" data-testid="memory-inspector">
    <template v-if="doc">
      <header><div><span>记忆 #{{ doc.id }}</span><strong>{{ doc.type || '记忆' }}</strong><small>第 {{ doc.revision ?? 1 }} 版 · {{ docScopeLabel(doc) }}</small></div><el-tag size="small" :type="stateTone">{{ stateLabel }}</el-tag></header>
      <label><span>文档内容</span><el-input :model-value="draft.text" data-testid="memory-inspector-text" type="textarea" :rows="5" resize="none" @update:model-value="updateDraft('text', String($event))" /><small class="field-hint">保存会追加新版本；来源和审计记录保留。</small></label>
      <div class="field-grid">
        <label><span>类型</span><el-input :model-value="draft.type" size="small" @update:model-value="updateDraft('type', String($event))" /></label>
        <label><span>层级</span><el-select :model-value="draft.layer" size="small" @update:model-value="updateDraft('layer', String($event))"><el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" /></el-select></label>
        <label><span>来源</span><el-select :model-value="draft.source" size="small" @update:model-value="updateDraft('source', String($event))"><el-option v-for="option in sourceOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></label>
      </div>
      <div class="time-grid">
        <label><span>生效时间</span><el-input :model-value="draft.validFrom" data-testid="memory-valid-from" type="datetime-local" size="small" @update:model-value="updateDraft('validFrom', String($event))" /></label>
        <label><span>失效时间</span><el-input :model-value="draft.validTo" data-testid="memory-valid-to" type="datetime-local" size="small" @update:model-value="updateDraft('validTo', String($event))" /></label>
        <label><span>过期时间</span><el-input :model-value="draft.expiresAt" data-testid="memory-expires-at" type="datetime-local" size="small" @update:model-value="updateDraft('expiresAt', String($event))" /></label>
      </div>
      <details><summary>重要度与置信度</summary><div class="slider-grid"><label><span>重要度 {{ draft.importance.toFixed(2) }}</span><el-slider :model-value="draft.importance" :min="0" :max="1" :step="0.05" @update:model-value="updateDraft('importance', Number($event))" /></label><label><span data-testid="memory-inspector-confidence">置信度 {{ draft.confidence.toFixed(2) }}</span><el-slider :model-value="draft.confidence" :min="0" :max="1" :step="0.05" @update:model-value="updateDraft('confidence', Number($event))" /></label></div></details>
      <div class="actions"><div class="save-state" :class="{ dirty }" role="status">{{ dirty ? '有未保存修改' : '已保存' }}</div><el-button data-testid="memory-inspector-save" size="small" type="primary" :loading="saving" :disabled="!dirty || !draft.text.trim()" @click="emit('save')">保存修改</el-button><el-button size="small" plain :disabled="!dirty" @click="emit('reset')">重置</el-button><el-button data-testid="memory-inspector-forget" size="small" type="warning" plain :loading="forgetting" :disabled="forgetting" @click="emit('forget', doc.id)">停止召回</el-button></div>
      <dl><div><dt>作用域</dt><dd data-testid="memory-inspector-scope">{{ docScopeLabel(doc) }}</dd></div><div><dt>来源</dt><dd data-testid="memory-inspector-source">{{ docSourceLabel(doc) }}</dd></div><div><dt>质量</dt><dd>{{ qualityPercent(doc) }}</dd></div></dl>
      <details v-if="evidenceIds.length"><summary>依据与关联（{{ evidenceIds.length }}）</summary><div class="evidence-list" data-testid="memory-inspector-evidence"><span v-for="id in evidenceIds" :key="id">{{ id }}</span></div></details>
      <details><summary>调整记忆层级</summary><div class="layer-actions"><button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="doc.layer === layer.value" @click="emit('move-layer', { doc, layer: layer.value })">{{ layer.label }}</button></div></details>
      <details><summary>技术信息</summary><pre>{{ metadataPreview(doc) }}</pre></details>
      <details v-if="auditEntries(doc).length"><summary>审计记录</summary><div class="audit"><div v-for="(entry, index) in auditEntries(doc)" :key="index"><strong>{{ auditActionLabel(entry.action) }}</strong><span>{{ auditEntrySummary(entry) }}</span></div></div></details>
      <details v-if="versionHistory.length"><summary>版本历史（{{ versionHistory.length }}）</summary><div class="versions"><article v-for="entry in versionHistory" :key="entry.revision"><div><strong>版本 {{ entry.revision }}</strong><span>{{ versionTimestamp(entry) }}</span></div><p>{{ entry.text || '无文本快照' }}</p><el-button :data-testid="`memory-rollback-${entry.revision}`" size="small" plain :loading="rollingBackRevision === entry.revision" :disabled="rollingBackRevision !== null" @click="rollback(entry.revision)">恢复此版本</el-button></article></div></details>
      <div class="secondary-actions"><el-button size="small" link type="primary" @click="emit('edit', doc)">完整编辑</el-button><el-button size="small" link @click="emit('boost', doc)">提高重要度</el-button></div>
      <details class="danger-zone"><summary>永久删除</summary><el-button data-testid="memory-inspector-delete" size="small" type="danger" plain :loading="removing" :disabled="removing" @click="emit('remove', doc.id)">永久删除</el-button></details>
    </template>
    <el-empty v-else description="选择一条记忆查看详情" :image-size="56" />
  </aside>
</template>

<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { memoryInspectorActionsKey } from './memory-panel-types'
import type { MemoryDoc, MemoryInspectorDraft, MemoryLayer, MemoryOption, MemoryVersionSnapshot } from './memory-panel-types'

const props = defineProps<{ doc: MemoryDoc | null; draft: MemoryInspectorDraft; layers: MemoryLayer[]; sourceOptions: MemoryOption[]; dirty: boolean; saving: boolean; forgetting: boolean; removing: boolean; docScopeLabel:(doc:MemoryDoc)=>string; docSourceLabel:(doc:MemoryDoc)=>string; qualityPercent:(doc:MemoryDoc)=>string; metadataPreview:(doc:MemoryDoc)=>string; auditEntries:(doc:MemoryDoc)=>Array<Record<string,unknown>>; auditActionLabel:(value:unknown)=>string; auditEntrySummary:(entry:Record<string,unknown>)=>string }>()
const emit = defineEmits<{ save:[]; reset:[]; edit:[doc:MemoryDoc]; boost:[doc:MemoryDoc]; forget:[id:string]; remove:[id:string]; 'move-layer':[payload:{doc:MemoryDoc;layer:string}]; 'update-draft':[value:Partial<MemoryInspectorDraft>] }>()
const inspectorActions = inject(memoryInspectorActionsKey, null)
const rollingBackRevision = ref<number | null>(null)
const stateLabels: Record<string, string> = { active: '当前有效', forgotten: '已停止召回', expired: '已过期', scheduled: '定时生效', superseded: '已被替代', rejected: '已拒绝', invalid: '需要检查' }
const stateLabel = computed(() => stateLabels[String(props.doc?.state || 'active')] || '当前有效')
const stateTone = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  const state = String(props.doc?.state || 'active')
  if (state === 'active') return 'success'
  if (state === 'forgotten' || state === 'expired' || state === 'scheduled') return 'warning'
  if (state === 'invalid' || state === 'rejected') return 'danger'
  return 'info'
})

const updateDraft = <K extends keyof MemoryInspectorDraft>(key: K, value: MemoryInspectorDraft[K]) => emit('update-draft', { [key]: value })
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
const rollback = async (revision: number) => {
  if (!props.doc || !inspectorActions || rollingBackRevision.value !== null) return
  rollingBackRevision.value = revision
  try {
    await inspectorActions.rollback(props.doc, revision)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '版本恢复失败')
  } finally {
    rollingBackRevision.value = null
  }
}
</script>

<style scoped>
.inspector { container-type: inline-size; display: flex; min-width: 0; flex-direction: column; gap: 14px; padding: 16px; background: var(--yui-surface); }.inspector header,.actions,.secondary-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.inspector header div,.inspector label,.audit div { display: flex; min-width: 0; flex-direction: column; gap: 5px; }.inspector header span,label>span,summary,dt { color: var(--yui-muted); font-size: 11px; }.inspector header strong { color: var(--yui-text); font-size: 16px; }.inspector header small { color: var(--yui-muted); font-size: 10px; }.field-hint { margin: 0; color: var(--yui-muted); font-size: 11px; line-height: 1.45; }.field-grid,.time-grid,.slider-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }.field-grid,.time-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }.field-grid :deep(.el-select),.time-grid :deep(.el-input) { width: 100%; min-width: 0; }.time-grid :deep(.el-input__wrapper),.time-grid :deep(.el-input__inner) { min-width: 0; }.actions { justify-content: flex-start; flex-wrap: wrap; }.save-state { margin-right: auto; color: var(--yui-muted); font-size: 11px; }.save-state.dirty { color: var(--yui-accent); font-weight: 600; }dl { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; margin: 0; }dl div { padding: 8px; background: var(--yui-surface-muted); border-radius: var(--yui-radius-control); }dd { margin: 3px 0 0; color: var(--yui-text); font-size: 12px; }.layer-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }.layer-actions button { min-height: 30px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); background: var(--yui-surface); color: var(--yui-text); cursor:pointer; }.layer-actions button[aria-pressed="true"] { border-color:var(--yui-accent);background:var(--yui-accent-soft); }details summary { cursor:pointer; }pre { max-height:220px; overflow:auto; padding:10px; background:var(--yui-surface-muted); color:var(--yui-text); white-space:pre-wrap; overflow-wrap:anywhere; font-size:11px; }.audit { display:grid;gap:8px;margin-top:8px; }.audit span { color:var(--yui-muted);font-size:11px; }.versions{display:grid;gap:8px;margin-top:8px}.versions article{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 10px;padding:10px;background:var(--yui-surface-muted);border-radius:var(--yui-radius-control)}.versions article div{display:flex;align-items:center;gap:8px}.versions article span{color:var(--yui-muted);font-size:10px}.versions article p{grid-column:1;margin:0;overflow-wrap:anywhere;color:var(--yui-text);font-size:11px}.versions article :deep(.el-button){grid-column:2;grid-row:1/3}.secondary-actions { justify-content:flex-start; }.danger-zone { padding-top:10px;border-top:1px solid var(--yui-border); }.danger-zone :deep(.el-button){margin-top:10px}
@container (max-width: 520px){.field-grid,.time-grid,.slider-grid,dl{grid-template-columns:1fr;}}
@media(max-width:620px){.field-grid,.time-grid,.slider-grid,dl{grid-template-columns:1fr;}.versions article{grid-template-columns:1fr}.versions article :deep(.el-button){grid-column:1;grid-row:auto;justify-self:start}}
</style>

<template>
  <section class="library" aria-labelledby="memory-library-title">
    <div class="library-heading">
      <div><h3 id="memory-library-title">记忆文档</h3><p role="status" aria-live="polite">{{ filteredCount }} 条</p></div>
<el-input :model-value="searchText" clearable placeholder="搜索记忆内容" class="search-input" aria-label="搜索记忆内容" @update:model-value="emit('update:searchText', String($event))" />
    </div>
    <div class="filter-toolbar" aria-label="记忆筛选">
      <div class="view-tabs" role="group" aria-label="记忆视图">
        <button v-for="option in viewOptions" :key="option.value" type="button" :aria-pressed="viewMode === option.value" @click="emit('update:viewMode', option.value)">{{ option.label }} <span>{{ docViewCount(option.value) }}</span></button>
      </div>
      <el-select :model-value="filterLayer" size="small" clearable placeholder="全部层级" aria-label="按层级筛选" @update:model-value="emit('update:filterLayer', String($event || ''))">
        <el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" />
      </el-select>
      <el-select :model-value="sortMode" size="small" aria-label="排序方式" @update:model-value="emit('update:sortMode', $event as DocSortMode)">
        <el-option label="最近更新" value="updated" /><el-option label="重要度" value="importance" /><el-option label="质量" value="quality" /><el-option label="置信度" value="confidence" />
      </el-select>
    </div>
      <div v-if="hasFilters" class="batch-toolbar" role="status">
        <div class="batch-summary"><strong>筛选结果</strong><span>{{ batchActionHint }}</span></div>
      <div class="batch-actions"><el-button size="small" plain @click="emit('reset-filters')">清空筛选</el-button><el-button size="small" plain :loading="batchActionLoading" :disabled="batchActionDisabled" @click="emit('batch-boost')">提高重要度</el-button><el-button size="small" type="danger" plain :loading="batchActionLoading" :disabled="batchActionDisabled" @click="emit('batch-delete')">{{ batchDeleteLabel }}</el-button></div>
    </div>
    <AsyncState :loading="loading" :error="error" :empty="filteredCount === 0" empty-text="暂无匹配的记忆" @retry="emit('retry')">
      <div class="master-detail">
        <div class="memory-list" role="listbox" aria-label="记忆列表">
          <button v-for="doc in visibleDocs" :key="doc.id" type="button" role="option" class="memory-row" :aria-selected="selectedDoc?.id === doc.id" :class="{ hit: isQueryHit(doc) }" :data-memory-id="doc.id" @click="emit('select', doc)">
            <span class="doc-title"><strong>{{ doc.type || '记忆' }}</strong><el-tag size="small" :type="stateTagType(doc.state)">{{ memoryStateLabel(doc.state) }}</el-tag></span>
            <p>{{ doc.text }}</p>
            <span class="doc-meta"><span>{{ doc.layer || '未分类' }}</span><span>{{ docSourceLabel(doc) }}</span><span>{{ docUpdatedLabel(doc) }}</span></span>
          </button>
          <button v-if="remainingCount" type="button" class="show-more" @click="emit('show-more')">再显示 {{ remainingCount }} 条</button>
        </div>
        <MemoryInspector
          :doc="selectedDoc" :draft="inspectorDraft" :layers="layers" :source-options="sourceOptions"
          :dirty="inspectorDraftDirty" :saving="inspectorDraftSaving" :forgetting="Boolean(selectedDoc && forgettingDocIds.has(selectedDoc.id))" :removing="Boolean(selectedDoc && removingDocIds.has(selectedDoc.id))"
          :doc-scope-label="docScopeLabel" :doc-source-label="docSourceLabel" :quality-percent="qualityPercent"
          :metadata-preview="metadataPreview" :audit-entries="docAuditEntries" :audit-action-label="auditActionLabel" :audit-entry-summary="auditEntrySummary" :operations="operations" :operations-loading="operationsLoading" :operations-error="operationsError"
          @save="emit('save-inspector')" @reset="emit('reset-inspector')" @edit="emit('edit', $event)" @boost="emit('boost', $event)" @forget="emit('forget', $event)" @remove="emit('remove', $event)" @move-layer="emit('move-layer', $event.doc, $event.layer)"
          @update-draft="emit('update-inspector-draft', $event)"
        />
      </div>
    </AsyncState>
  </section>
</template>

<script setup lang="ts">
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import MemoryInspector from './MemoryInspector.vue'
import type { MemoryOperation } from '@/api/clients/memory-client'
import type { DocSortMode, DocViewMode, MemoryDoc, MemoryInspectorDraft, MemoryLayer, MemoryOption, TagType } from './memory-panel-types'

defineProps<{
  visibleDocs: MemoryDoc[]; filteredCount: number; remainingCount: number; selectedDoc: MemoryDoc | null
  viewMode: DocViewMode; sortMode: DocSortMode; filterLayer: string; searchText: string
  viewOptions: Array<{ value: DocViewMode; label: string }>; layers: MemoryLayer[]; sourceOptions: MemoryOption[]
  loading: boolean; error?: string; hasFilters: boolean; batchActionHint: string; batchDeleteLabel: string
  batchActionLoading: boolean; batchActionDisabled: boolean; inspectorDraft: MemoryInspectorDraft; inspectorDraftDirty: boolean
  inspectorDraftSaving: boolean; forgettingDocIds: Set<string>; removingDocIds: Set<string>
  docViewCount: (mode: DocViewMode) => number; isQueryHit: (doc: MemoryDoc) => boolean; layerTagType: (layer?: string) => TagType
  formatScore: (value?: number | null) => string; docUpdatedLabel: (doc: MemoryDoc) => string; docScopeLabel: (doc: MemoryDoc) => string
  docSourceLabel: (doc: MemoryDoc) => string; qualityPercent: (doc: MemoryDoc) => string; metadataPreview: (doc: MemoryDoc) => string
  docAuditEntries: (doc: MemoryDoc) => Array<Record<string, unknown>>; auditActionLabel: (value: unknown) => string; auditEntrySummary: (entry: Record<string, unknown>) => string
  operations: MemoryOperation[]; operationsLoading: boolean; operationsError?: string | null
}>()

const emit = defineEmits<{
  'update:viewMode': [value: DocViewMode]; 'update:sortMode': [value: DocSortMode]; 'update:filterLayer': [value: string]; 'update:searchText': [value: string]
  select: [doc: MemoryDoc]; edit: [doc: MemoryDoc]; boost: [doc: MemoryDoc]; forget: [id: string]; remove: [id: string]; 'move-layer': [doc: MemoryDoc, layer: string]
  retry: []; 'show-more': []; 'reset-filters': []; 'batch-boost': []; 'batch-delete': []; 'save-inspector': []; 'reset-inspector': []; 'update-inspector-draft': [value: Partial<MemoryInspectorDraft>]
}>()

const memoryStateLabels: Record<string, string> = { active: '有效', forgotten: '已停止', expired: '已过期', scheduled: '待生效', superseded: '已替代', rejected: '已拒绝', invalid: '需检查' }
const memoryStateLabel = (state?: string) => memoryStateLabels[String(state || 'active')] || '有效'
const stateTagType = (state?: string): TagType => {
  const value = String(state || 'active')
  if (value === 'active') return 'success'
  if (value === 'forgotten' || value === 'expired' || value === 'scheduled') return 'warning'
  if (value === 'invalid' || value === 'rejected') return 'danger'
  return 'info'
}
</script>

<style scoped>
.library { display: flex; min-height: 0; flex-direction: column; gap: 14px; }.library-heading,.filter-toolbar,.batch-toolbar,.doc-title,.doc-meta { display: flex; align-items: center; gap: 10px; }.library-heading,.batch-toolbar { justify-content: space-between; }.library-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.library-heading p,.batch-toolbar span { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }.library-tip { display: block; margin-top: 4px; color: var(--yui-muted); font-size: 11px; }.search-input { width: min(360px, 48%); }.filter-toolbar { flex-wrap: wrap; }.view-tabs { display: flex; flex: 1; gap: 4px; flex-wrap: wrap; }.view-tabs button { min-height: 32px; padding: 5px 10px; border: 1px solid transparent; border-radius: var(--yui-radius-control); background: transparent; color: var(--yui-muted); cursor: pointer; }.view-tabs button[aria-pressed="true"] { border-color: var(--yui-border-strong); background: var(--yui-surface-muted); color: var(--yui-text); }.view-tabs span { font-size: 11px; }.batch-toolbar { align-items: center; padding: 9px 10px; background: var(--yui-warning-soft); border-radius: var(--yui-radius-card); }.batch-summary { display: flex; min-width: 0; flex-direction: column; gap: 2px; }.batch-summary strong { color: var(--yui-text); font-size: 12px; }.batch-actions { display: flex; flex-wrap: wrap; gap: 6px; }.master-detail { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(360px, 1.1fr); min-height: 430px; border-top: 1px solid var(--yui-border); }.memory-list { min-width: 0; max-height: 620px; padding: 6px; overflow-y: auto; border-right: 1px solid var(--yui-border); background: var(--yui-surface-muted); }.memory-list > button { display: flex; width: 100%; flex-direction: column; gap: 7px; margin-bottom: 6px; padding: 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface); color: var(--yui-text); text-align: left; cursor: pointer; }.memory-list > button:hover,.memory-list > button[aria-selected="true"] { background: var(--yui-surface-muted); }.memory-list > button[aria-selected="true"] { border-color: var(--yui-accent); box-shadow: inset 3px 0 0 var(--yui-accent); }.memory-list > button.hit { background: var(--yui-success-soft); }.doc-title { justify-content: space-between; }.memory-list p { display: -webkit-box; margin: 0; overflow: hidden; font-size: 13px; line-height: 1.5; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }.doc-meta { flex-wrap: wrap; color: var(--yui-muted); font-size: 10px; }.show-more { align-items: center !important; margin-bottom: 0 !important; border: 0 !important; background: transparent !important; color: var(--yui-accent) !important; }.memory-list button:focus-visible,.view-tabs button:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: -2px; }
@media (max-width: 900px) { .master-detail { grid-template-columns: 1fr; }.memory-list { max-height: 380px; border-right: 0; border-bottom: 1px solid var(--yui-border); }.search-input { width: 100%; }.library-heading { align-items: stretch; flex-direction: column; } }
@media (max-width: 620px) { .batch-toolbar { align-items: flex-start; flex-direction: column; }.batch-actions { width: 100%; }.batch-actions :deep(.el-button) { flex: 1; }.filter-toolbar :deep(.el-select) { width: calc(50% - 5px); }.view-tabs { flex-basis: 100%; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition-duration: 0.01ms !important; } }
</style>

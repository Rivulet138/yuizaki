<template>
  <section class="library" aria-labelledby="memory-library-title">
    <div class="library-heading">
      <div><h3 id="memory-library-title">{{ t('memoryView.libraryTitle') }}</h3><span class="count-label" role="status" aria-live="polite">{{ t('memoryView.countItems', { count: filteredCount }) }}</span></div>
<el-input :model-value="searchText" clearable :placeholder="t('memoryView.librarySearchPlaceholder')" class="search-input" :aria-label="t('memoryView.librarySearchAria')" @update:model-value="emit('update:searchText', String($event))" />
    </div>
    <details class="filter-disclosure" :open="filterDisclosureOpen" @toggle="syncFilterDisclosure">
      <summary>{{ t('memoryView.libraryFilters') }} <span v-if="hasFilters">{{ t('memoryView.libraryFiltersActive') }}</span></summary>
      <div class="filter-toolbar" :aria-label="t('memoryView.libraryFiltersAria')">
        <div class="view-tabs" role="group" :aria-label="t('memoryView.libraryViewsAria')">
          <button v-for="option in viewOptions" :key="option.value" type="button" :aria-pressed="viewMode === option.value" @click="emit('update:viewMode', option.value)">{{ option.label }} <span>{{ docViewCount(option.value) }}</span></button>
        </div>
        <el-select :model-value="filterLayer" size="small" clearable :placeholder="t('memoryView.libraryAllLayers')" :aria-label="t('memoryView.libraryFilterLayerAria')" @update:model-value="emit('update:filterLayer', String($event || ''))">
          <el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" />
        </el-select>
        <el-select :model-value="sortMode" size="small" :aria-label="t('memoryView.librarySortAria')" @update:model-value="emit('update:sortMode', $event as DocSortMode)">
          <el-option :label="t('memoryView.sortUpdated')" value="updated" /><el-option :label="t('memoryView.sortImportance')" value="importance" /><el-option :label="t('memoryView.reliability')" value="quality" /><el-option :label="t('memoryView.sortConfidence')" value="confidence" />
        </el-select>
      </div>
    </details>
      <div v-if="hasFilters" class="batch-toolbar" role="toolbar" :aria-label="t('memoryView.libraryBatchAria')">
      <div class="batch-actions"><el-button size="small" plain @click="emit('reset-filters')">{{ t('memoryView.clearFilters') }}</el-button><el-button size="small" plain :loading="batchActionLoading" :disabled="batchActionDisabled" @click="emit('batch-boost')">{{ t('memoryView.boostImportance') }}</el-button><el-button size="small" type="danger" plain :loading="batchActionLoading" :disabled="batchActionDisabled" @click="emit('batch-delete')">{{ batchDeleteLabel }}</el-button></div>
    </div>
    <AsyncState
      :loading="loading"
      :error="error"
      :empty="filteredCount === 0"
      :error-title="t('memoryView.libraryUnavailable')"
      :retry-text="t('memoryView.libraryReconnect')"
      :empty-text="hasFilters ? t('memoryView.libraryEmptyFiltered') : t('memoryView.libraryEmpty')"
      @retry="emit('retry')"
    >
      <template #empty>
        <p class="library-empty-hint">
          {{ hasFilters ? t('memoryView.libraryEmptyHintFiltered') : t('memoryView.libraryEmptyHint') }}
        </p>
        <el-button v-if="hasFilters" size="small" plain @click="emit('reset-filters')">{{ t('memoryView.clearFilters') }}</el-button>
      </template>
      <div class="master-detail">
        <div class="memory-list" role="listbox" :aria-label="t('memoryView.libraryListAria')">
          <button v-for="doc in visibleDocs" :key="doc.id" type="button" role="option" class="memory-row" :aria-selected="selectedDoc?.id === doc.id" :class="{ hit: isQueryHit(doc) }" :data-memory-id="doc.id" @click="emit('select', doc)">
            <span class="doc-title"><strong>{{ docTypeLabel(doc.type) }}</strong><el-tag size="small" :type="stateTagType(doc.state)">{{ memoryStateLabel(doc.state) }}</el-tag></span>
            <p>{{ doc.text }}</p>
            <span class="doc-meta"><span>{{ layerLabel(doc.layer) }}</span><span>{{ docSourceLabel(doc) }}</span><span>{{ docUpdatedLabel(doc) }}</span></span>
          </button>
          <button v-if="remainingCount" type="button" class="show-more" @click="emit('show-more')">{{ t('memoryView.libraryShowMore', { count: remainingCount }) }}</button>
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
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElButton, ElInput, ElOption, ElSelect, ElTag } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { t } from '@/i18n'
import MemoryInspector from './MemoryInspector.vue'
import { computed, ref, watch } from 'vue'
import type { MemoryOperation } from '@/api/clients/memory-client'
import type { DocSortMode, DocViewMode, MemoryDoc, MemoryInspectorDraft, MemoryLayer, MemoryOption, TagType } from './memory-panel-types'

const props = defineProps<{
  visibleDocs: MemoryDoc[]; filteredCount: number; remainingCount: number; selectedDoc: MemoryDoc | null
  viewMode: DocViewMode; sortMode: DocSortMode; filterLayer: string; searchText: string
  viewOptions: Array<{ value: DocViewMode; label: string }>; layers: MemoryLayer[]; sourceOptions: MemoryOption[]
  loading: boolean; error?: string; hasFilters: boolean; batchDeleteLabel: string
  batchActionLoading: boolean; batchActionDisabled: boolean; inspectorDraft: MemoryInspectorDraft; inspectorDraftDirty: boolean
  inspectorDraftSaving: boolean; forgettingDocIds: Set<string>; removingDocIds: Set<string>
  docViewCount: (mode: DocViewMode) => number; isQueryHit: (doc: MemoryDoc) => boolean; layerTagType: (layer?: string) => TagType
  formatScore: (value?: number | null) => string; docUpdatedLabel: (doc: MemoryDoc) => string; docScopeLabel: (doc: MemoryDoc) => string
  docSourceLabel: (doc: MemoryDoc) => string; qualityPercent: (doc: MemoryDoc) => string; metadataPreview: (doc: MemoryDoc) => string
  docAuditEntries: (doc: MemoryDoc) => Array<Record<string, unknown>>; auditActionLabel: (value: unknown) => string; auditEntrySummary: (entry: Record<string, unknown>) => string
  operations: MemoryOperation[]; operationsLoading: boolean; operationsError?: string | null
}>()

const filterDisclosureOpen = ref(props.hasFilters)
watch(() => props.hasFilters, (active) => {
  if (active) filterDisclosureOpen.value = true
})
const syncFilterDisclosure = (event: Event) => {
  filterDisclosureOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

const emit = defineEmits<{
  'update:viewMode': [value: DocViewMode]; 'update:sortMode': [value: DocSortMode]; 'update:filterLayer': [value: string]; 'update:searchText': [value: string]
  select: [doc: MemoryDoc]; edit: [doc: MemoryDoc]; boost: [doc: MemoryDoc]; forget: [id: string]; remove: [id: string]; 'move-layer': [doc: MemoryDoc, layer: string]
  retry: []; 'show-more': []; 'reset-filters': []; 'batch-boost': []; 'batch-delete': []; 'save-inspector': []; 'reset-inspector': []; 'update-inspector-draft': [value: Partial<MemoryInspectorDraft>]
}>()

const memoryStateLabels = computed<Record<string, string>>(() => ({
  active: t('memoryView.availableForChat'),
  forgotten: t('memoryView.paused'),
  expired: t('memoryView.stateExpired'),
  scheduled: t('memoryView.stateScheduled'),
  superseded: t('memoryView.stateSuperseded'),
  rejected: t('memoryView.stateRejected'),
  invalid: t('memoryView.stateInvalid'),
}))
const memoryStateLabel = (state?: string) => memoryStateLabels.value[String(state || 'active')] || t('memoryView.availableForChat')
const docTypeLabels = computed<Record<string, string>>(() => ({
  fact: t('memoryView.docTypeFact'),
  preference: t('memoryView.docTypePreference'),
  event: t('memoryView.docTypeEvent'),
  promise: t('memoryView.docTypePromise'),
  taboo: t('memoryView.docTypeTaboo'),
  summary: t('memoryView.docTypeSummary'),
  chat: t('memoryView.docTypeChat'),
}))
const docTypeLabel = (type?: string) => docTypeLabels.value[String(type || '')] || type || t('memoryView.memoryFallback')
const layerLabel = (value?: string) => props.layers.find(layer => layer.value === value)?.label || t('memoryView.uncategorized')
const stateTagType = (state?: string): TagType => {
  const value = String(state || 'active')
  if (value === 'active') return 'success'
  if (value === 'forgotten' || value === 'expired' || value === 'scheduled') return 'warning'
  if (value === 'invalid' || value === 'rejected') return 'danger'
  return 'info'
}
</script>

<style scoped>
.library { display: flex; min-height: 0; flex-direction: column; gap: 14px; }.library-heading,.filter-toolbar,.batch-toolbar,.doc-title,.doc-meta { display: flex; align-items: center; gap: 10px; }.library-heading,.batch-toolbar { justify-content: space-between; }.library-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.count-label { color: var(--yui-muted); font-size: 12px; }.search-input { width: min(360px, 48%); }.filter-disclosure { border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-muted); }.filter-disclosure summary { display: flex; align-items: center; justify-content: space-between; padding: 9px 12px; color: var(--yui-text); font-size: 12px; font-weight: 700; cursor: pointer; }.filter-disclosure summary span { color: var(--yui-accent); font-weight: 600; }.filter-toolbar { flex-wrap: wrap; padding: 0 12px 12px; }.view-tabs { display: flex; flex: 1; gap: 4px; flex-wrap: wrap; }.view-tabs button { min-height: 32px; padding: 5px 10px; border: 1px solid transparent; border-radius: var(--yui-radius-control); background: transparent; color: var(--yui-muted); cursor: pointer; }.view-tabs button[aria-pressed="true"] { border-color: var(--yui-border-strong); background: var(--yui-surface); color: var(--yui-text); }.view-tabs span { font-size: 11px; }.batch-toolbar { align-items: center; justify-content: flex-end; padding: 9px 10px; background: var(--yui-warning-soft); border-radius: var(--yui-radius-card); }.batch-actions { display: flex; flex-wrap: wrap; gap: 6px; }.library-empty-hint { max-width: 420px; margin: 0 auto 10px; color: var(--yui-muted); font-size: 12px; line-height: 1.6; text-align: center; }
.master-detail { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(360px, 1.1fr); min-height: 430px; border-top: 1px solid var(--yui-border); }.memory-list { min-width: 0; max-height: 620px; padding: 6px; overflow-y: auto; border-right: 1px solid var(--yui-border); background: var(--yui-surface-muted); }.memory-list > button { display: flex; width: 100%; flex-direction: column; gap: 7px; margin-bottom: 6px; padding: 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface); color: var(--yui-text); text-align: left; cursor: pointer; }.memory-list > button:hover,.memory-list > button[aria-selected="true"] { background: var(--yui-surface-muted); }.memory-list > button[aria-selected="true"] { border-color: var(--yui-accent); box-shadow: inset 3px 0 0 var(--yui-accent); }.memory-list > button.hit { background: var(--yui-success-soft); }.doc-title { justify-content: space-between; }.memory-list p { display: -webkit-box; margin: 0; overflow: hidden; font-size: 13px; line-height: 1.5; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }.doc-meta { flex-wrap: wrap; color: var(--yui-muted); font-size: 10px; }.show-more { align-items: center !important; margin-bottom: 0 !important; border: 0 !important; background: transparent !important; color: var(--yui-accent) !important; }.memory-list button:focus-visible,.view-tabs button:focus-visible,.filter-disclosure summary:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: -2px; }
@media (max-width: 900px) { .master-detail { grid-template-columns: 1fr; }.memory-list { max-height: 380px; border-right: 0; border-bottom: 1px solid var(--yui-border); }.search-input { width: 100%; }.library-heading { align-items: stretch; flex-direction: column; } }
@media (max-width: 620px) { .batch-toolbar { align-items: flex-start; flex-direction: column; }.batch-actions { width: 100%; }.batch-actions :deep(.el-button) { flex: 1; }.filter-toolbar :deep(.el-select) { width: calc(50% - 5px); }.view-tabs { flex-basis: 100%; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition-duration: 0.01ms !important; } }
</style>

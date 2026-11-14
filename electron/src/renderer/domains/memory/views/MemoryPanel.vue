
<template>
  <PanelShell :title="t('memoryPanel.title')" tone="companion" density="compact">
    <template #actions>
      <label class="scope-control"><span>{{ t('memoryPanel.scopeLabel') }}</span><el-select :model-value="currentMemoryScope" size="small" :disabled="workspaceScopeSaving" :aria-label="t('memoryPanel.scopeAria')" @change="updateDefaultMemoryScope"><el-option v-for="scope in memoryScopeOptions" :key="scope.value" :label="scope.label" :value="scope.value" :disabled="scope.value === 'session' && !sessionStore.activeSession" /></el-select></label>
      <el-dropdown trigger="click" @command="handleAdvancedToolCommand">
        <el-button data-testid="memory-advanced-tools-toggle" plain :icon="Tools" :type="advancedToolsVisible ? 'primary' : 'default'" :aria-label="t('memoryPanel.advancedToolsAria')" :aria-expanded="advancedToolsVisible">{{ t('memoryPanel.advancedToolsLabel') }}</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="open-index">{{ t('memoryPanel.advancedIndexTools') }}</el-dropdown-item>
            <el-dropdown-item command="export" :disabled="exportLoading">{{ t('memoryPanel.exportCurrentScope') }}</el-dropdown-item>
            <el-dropdown-item command="import" :disabled="importLoading">{{ t('memoryPanel.importBackup') }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <input ref="memoryImportInput" class="memory-import-input" type="file" accept="application/json,.json" :aria-label="t('memoryPanel.importFileAria')" @change="handleMemoryImportFile" />
      <el-button data-testid="memory-refresh" circle plain :icon="Refresh" :title="t('memoryPanel.refresh')" :aria-label="t('memoryPanel.refresh')" :loading="memoryRefreshing || docsRequest.loading" @click="refreshMemoryState" />
    </template>

    <div class="memory-panel">
      <p v-if="docsRequest.error && hasScopedDocCache" role="alert">{{ docsRequest.error }}</p>
      <p v-if="exportReport" role="status">{{ exportReport }}</p>
      <p v-if="deletionReport" :role="deletionReport.warning ? 'alert' : 'status'">{{ deletionReport.message }}</p>
      <section v-if="importReport" class="memory-import-report" aria-live="polite">
        <div class="import-report-head">
          <strong>{{ t('memoryPanel.lastImportTitle') }}</strong>
          <el-button link size="small" @click="importReport = null">{{ t('memoryPanel.close') }}</el-button>
        </div>
        <p>{{ importTargetLabel }}</p>
        <div class="import-report-grid">
          <span>{{ t('memoryPanel.importWritten') }} <strong>{{ importReport.imported_count }}</strong> {{ t('memoryPanel.unitItems') }}</span>
          <span>{{ t('memoryPanel.importSkipped') }} <strong>{{ importReport.skipped_count }}</strong> {{ t('memoryPanel.unitItems') }}</span>
          <span>{{ t('memoryPanel.importRestored') }} <strong>{{ importReport.restored_soft_forgotten_count ?? 0 }}</strong> {{ t('memoryPanel.unitItems') }}</span>
          <span>{{ t('memoryPanel.importIndexStatus') }} <strong>{{ importReport.effects?.index === 'rebuild_required' ? t('memoryPanel.indexRebuildRequired') : t('memoryPanel.indexUnchanged') }}</strong></span>
        </div>
        <div v-if="importReport.skipped_count" class="import-report-reasons">
          <span v-for="(count, reason) in (importReport.skipped_reason_counts || {})" :key="reason">{{ importReasonLabel(reason) }}{{ t('memoryPanel.labelSeparator') }}{{ count }}</span>
        </div>
        <details v-if="importReport.skipped.length" class="import-report-details">
          <summary>{{ t('memoryPanel.importSkippedDetails', { count: importReport.skipped.length }) }}</summary>
          <ul>
            <li v-for="(item, index) in importReport.skipped.slice(0, 50)" :key="`${item.id || 'unknown'}-${index}`">
              <strong>{{ item.id || t('memoryPanel.thisRecord') }}</strong><span>{{ importReasonLabel(item.reason) }}</span><small v-if="item.detail">{{ compactText(String(item.detail), 120) }}</small>
            </li>
          </ul>
          <p v-if="importReport.skipped.length > 50">{{ t('memoryPanel.importSkippedTruncated', { count: importReport.skipped.length }) }}</p>
        </details>
      </section>
      <p v-if="deletePreflightLoading" role="status">{{ memoryText('正在预检删除影响…', 'Checking deletion effects…') }}</p>
      <p v-if="deletePreflightError" role="alert">{{ deletePreflightError }}</p>
      <details v-if="batchResults.length" class="memory-import-report" open>
        <summary>{{ memoryText('最近批处理逐项结果', 'Latest batch item results') }} · {{ batchContext }}</summary>
        <ul><li v-for="item in batchResults" :key="item.id"><code>{{ item.id }}</code> · {{ item.status }} · {{ item.detail }}</li></ul>
      </details>
      <nav class="memory-tabs" role="tablist" :aria-label="t('memoryPanel.tabsAria')">
        <button v-for="(tab, index) in memoryTabs" :id="`memory-tab-${tab.value}`" :key="tab.value" type="button" role="tab" :tabindex="activeTab === tab.value ? 0 : -1" :aria-selected="activeTab === tab.value" :aria-controls="`memory-panel-${tab.value}`" @click="activeTab = tab.value" @keydown="onMemoryTabKeydown($event, index)">
          <el-icon aria-hidden="true"><component :is="tab.icon" /></el-icon><span class="tab-label">{{ tab.label }}</span><span v-if="tab.count !== undefined" class="tab-count">{{ tab.count }}</span>
        </button>
      </nav>
      <div v-show="activeTab === 'library'" id="memory-panel-library" role="tabpanel" aria-labelledby="memory-tab-library" class="tab-panel">
        <MemoryLibrary
          :visible-docs="visibleDocs" :filtered-count="filteredDocs.length" :remaining-count="remainingFilteredDocCount" :selected-doc="selectedDoc"
          :view-mode="docViewMode" :sort-mode="docSortMode" :filter-layer="filterLayer" :search-text="searchText" :view-options="docViewOptions"
          :layers="layers" :source-options="memorySourceOptions" :loading="docsRequest.loading && !hasScopedDocCache" :error="hasScopedDocCache ? null : docsRequest.error"
          :has-filters="hasDocFilters" :batch-delete-label="batchDeleteLabel"
          :batch-action-loading="batchActionLoading || deletePreflightLoading" :batch-action-disabled="batchActionDisabled" :inspector-draft="inspectorDraft"
          :inspector-draft-dirty="inspectorDraftDirty" :inspector-draft-saving="inspectorDraftSaving" :forgetting-doc-ids="forgettingDocIds" :removing-doc-ids="removingDocIds"
          :doc-view-count="docViewCount" :is-query-hit="isQueryHit" :layer-tag-type="layerTagType" :format-score="formatScore"
          :doc-updated-label="docUpdatedLabel" :doc-scope-label="docScopeLabel" :doc-source-label="docSourceLabel" :quality-percent="qualityPercent"
          :metadata-preview="metadataPreview" :doc-audit-entries="docAuditEntries" :audit-action-label="auditActionLabel" :audit-entry-summary="auditEntrySummary" :operations="operations" :operations-loading="operationsRequest.loading" :operations-error="operationsRequest.error"
          @update:view-mode="docViewMode = $event" @update:sort-mode="docSortMode = $event" @update:filter-layer="filterLayer = $event" @update:search-text="searchText = $event"
          @select="selectDoc" @edit="openEditDoc" @boost="boostDocImportance" @forget="forgetDoc" @remove="removeDoc" @move-layer="moveDocLayer"
          @retry="loadScopedDocs" @show-more="showMoreDocs" @reset-filters="resetDocFilters" @batch-boost="batchBoostVisibleDocs"
          @batch-delete="batchDeleteVisibleDocs" @save-inspector="saveInspectorDraft" @reset-inspector="resetInspectorDraft"
          @update-inspector-draft="Object.assign(inspectorDraft, $event)"
        />
      </div>
      <div v-show="activeTab === 'review'" id="memory-panel-review" role="tabpanel" aria-labelledby="memory-tab-review" class="tab-panel"><MemoryReviewQueue :docs="reviewDocs" :compact-text="compactText" :quality-percent="qualityPercent" :processing-id="reviewProcessingId" :loading="candidatesRequest?.loading" :error="candidatesRequest?.error" @review="openEditDoc" @decide="decideReviewCandidate" @retry="refreshMemoryState" /></div>
      <div v-show="activeTab === 'overview'" id="memory-panel-overview" role="tabpanel" aria-labelledby="memory-tab-overview" class="tab-panel">
        <MemoryOverview
          :overview="overview" :forgotten-docs="forgottenDocs" :layers="layerStats" :selected-layer="filterLayer"
          :loading="overviewRequest.loading || forgottenDocsRequest.loading" :error="overviewRequest.error || forgottenDocsRequest.error"
          :restoring-doc-ids="restoringDocIds" @select-layer="openLayerInLibrary" @restore="restoreForgottenDoc" @retry="refreshMemoryState"
        />
      </div>
    </div>

    <el-drawer v-model="advancedToolsVisible" :title="t('memoryPanel.advancedDrawerTitle')" size="min(560px, 92vw)" append-to-body>
      <MemoryStorageStatus :status="indexStatus" :overview="overview" :scope="currentMemoryScope" :workspace-id="activeWorkspace.id" :session-id="sessionStore.activeSession?.id" />
      <MemoryAdvancedTools
        :feedback-by-id="feedbackById" :feedback-pending-ids="feedbackPendingIds" :feedback-errors="feedbackErrors" :rebuild-monitor-error="rebuildMonitorError"
        :index-status="indexStatus" :rebuild-job="displayedRebuildJob" :index-status-refreshing="indexStatusRefreshing" :index-status-label="indexStatusLabel" :index-availability-label="indexAvailabilityLabel" :index-status-tone="indexStatusTone"
        :doc-count="docs.length" :rebuild-index-loading="rebuildIndexLoading" :query-form="queryForm" :layers="layers"
        :effective-query-layers="effectiveQueryLayers" :query-loading="queryRequest.loading"
        :query-error="queryRequest.error" :query-result="queryResult" :query-summary="querySummary"
        :filter-reason-text="filterReasonText"
        :maintenance-policy="maintenancePolicy" :maintenance-preview="maintenancePreview"
        :maintenance-preview-matches-policy="maintenancePreviewMatchesPolicy" :maintenance-saving="maintenanceSaving"
        :maintenance-preview-loading="maintenancePreviewLoading" :maintenance-apply-loading="maintenanceApplyLoading"
        :format-latency="formatLatency" :compact-text="compactText" :maintenance-reason-label="maintenanceReasonLabel"
         @refresh-index-status="checkMemoryIndexStatus" @rebuild-index="rebuildMemoryIndex" @cancel-rebuild-index="cancelMemoryIndexRebuild" @query="submitQuery" @toggle-query-layer="toggleQueryLayer"
         @reset-query-layers="resetQueryLayers" @select-result="selectDocFromAdvanced"
         @feedback="handleRecallFeedback"
        @save-maintenance="saveMemoryPolicy" @preview-maintenance="previewMemoryMaintenance" @apply-maintenance="applyMemoryMaintenance"
        @update-query="Object.assign(queryForm, $event)" @update-maintenance="Object.assign(maintenancePolicy, $event)"
      />
    </el-drawer>

    <el-dialog v-model="editDialogVisible" :title="t('memoryPanel.editDialogTitle')" width="min(640px, 92vw)">
      <el-form label-position="top" @submit.prevent>
        <el-form-item :label="t('memoryPanel.editTextLabel')"><el-input v-model="editForm.text" type="textarea" :rows="5" /></el-form-item>
        <div class="dialog-grid"><el-form-item :label="t('memoryPanel.editLayerLabel')"><el-select v-model="editForm.layer"><el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" /></el-select></el-form-item><el-form-item :label="t('memoryPanel.editTypeLabel')"><el-input v-model="editForm.type" /></el-form-item></div>
        <div class="dialog-grid"><el-form-item :label="t('memoryPanel.editImportanceLabel', { percent: scorePercent(editForm.importance) })"><el-slider v-model="editForm.importance" :min="0" :max="1" :step="0.05" /></el-form-item><el-form-item :label="t('memoryPanel.editConfidenceLabel', { percent: scorePercent(editForm.confidence) })"><el-slider v-model="editForm.confidence" :min="0" :max="1" :step="0.05" /></el-form-item></div>
        <el-form-item :label="t('memoryPanel.editSourceLabel')"><el-select v-model="editForm.source"><el-option v-for="source in memorySourceOptions" :key="source.value" :label="source.label" :value="source.value" /></el-select></el-form-item>
        <details><summary>{{ t('memoryPanel.editMetadata') }}</summary><el-input v-model="editForm.metadataJson" type="textarea" :rows="4" /></details>
      </el-form>
      <template #footer><el-button @click="editDialogVisible = false">{{ t('memoryPanel.cancel') }}</el-button><el-button type="primary" :loading="updateRequest.loading" :disabled="!editForm.text.trim() || batchActionLoading || updateRequest.loading" @click="submitEditDoc">{{ t('memoryPanel.saveChanges') }}</el-button></template>
    </el-dialog>
  </PanelShell>
</template>


<script setup lang="ts">
import { ElIcon } from 'element-plus'
import 'element-plus/es/components/icon/style/css'
import { ElButton, ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/dropdown/style/css'
import { ElSlider } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElDialog, ElDrawer, ElForm, ElFormItem, ElInput, ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/drawer/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input/style/css'
import { Collection, DataAnalysis, Refresh, Tools, User } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import MemoryAdvancedTools from '../components/MemoryAdvancedTools.vue'
import MemoryStorageStatus from '../components/MemoryStorageStatus.vue'
import MemoryLibrary from '../components/MemoryLibrary.vue'
import MemoryOverview from '../components/MemoryOverview.vue'
import MemoryReviewQueue from '../components/MemoryReviewQueue.vue'
import { useMemoryDomain } from '../composables/useMemoryDomain'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { memoryClient } from '@/api/clients/memory-client'
import type { MemoryDeletePreview, MemoryImportResult, MemoryIndexRebuildJob, MemoryIndexStatus, MemoryMaintenancePolicyPayload, MemoryMaintenancePreview } from '@/api/clients/memory-client'
import { getMemoryIndexUiStatus } from '../memory-index-status'
import type { MemoryDoc } from '../composables/useMemoryDomain'
import { memoryText, memoryIndexLabel, memoryDeletionNote, memoryIndexCleanupStatus, memoryDeletionResultText } from '../memory-feedback'
import { memoryInspectorActionsKey } from '../components/memory-panel-types'
import { describeFailure } from '@/shared/errors/describe-error'
import { t } from '@/i18n'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type DocViewMode = 'all' | 'recallable' | 'review' | 'important' | 'hits'
type DocSortMode = 'updated' | 'importance' | 'quality' | 'confidence'
type MemoryScope = 'global' | 'workspace' | 'session'
type MemoryTab = 'library' | 'review' | 'overview'

const {
  invalidateReads, docs, docsScopeKey, operations, forgottenDocs, reviewCandidates, overview, queryResult,
  docsRequest, forgottenDocsRequest, overviewRequest, candidatesRequest, updateRequest, queryRequest, operationsRequest,
  loadDocs, loadForgottenDocs, loadCandidates, loadOperations, loadOverview, updateDoc, softForgetDoc, restoreDoc, reviewCandidate, queryMemory, recordRecallFeedback,
} = useMemoryDomain()
const route = useRoute()
const sessionStore = useSessionStore()
const workspaceStore = useWorkspaceStore()
const activeWorkspace = computed(() => workspaceStore.activeWorkspace)
const normalizeMemoryScope = (scope?: string | null): MemoryScope => {
  if (scope === 'global' || scope === 'session') return scope
  return 'workspace'
}
const currentMemoryScope = computed<MemoryScope>(() => {
  const scope = normalizeMemoryScope(activeWorkspace.value?.memory_scope)
  return scope === 'session' && !sessionStore.activeSession ? 'workspace' : scope
})
const memoryContextKey = () => JSON.stringify([currentMemoryScope.value, activeWorkspace.value.id, sessionStore.activeSession?.id])

const scopedDocOptions = () => ({
  scope: currentMemoryScope.value,
  workspaceId: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
  sessionId: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
})


const hasScopedDocCache = computed(() => {
  const options = scopedDocOptions()
  return docsScopeKey.value === JSON.stringify([options.scope, options.workspaceId, options.sessionId])
})

const indexStatus = ref<MemoryIndexStatus | null>(null)
const advancedToolsVisible = ref(false)
const reviewProcessingId = ref('')
const activeTab = ref<MemoryTab>('library')
const searchText = ref('')
const filterLayer = ref('')
const docViewMode = ref<DocViewMode>('all')
const docSortMode = ref<DocSortMode>('updated')
const selectedDocId = ref('')
const selectedQueryLayers = ref<string[]>([])
const queryForm = reactive({ query: '', scope: currentMemoryScope.value, top_k: 5, expand_relations: true, relation_limit: 20, relation_depth: 1 })
const editDialogVisible = ref(false)
const editForm = reactive({ id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual', metadataJson: '' })
const editTarget = ref<MemoryDoc | null>(null)
let editContext = ''
let editDraftKey = ''
let editBaseSnapshot = ''
const editDrafts = new Map<string, { form: typeof editForm; base: string }>()
const cacheEditDraft = () => {
  if (!editDraftKey) return
  if (JSON.stringify(editForm) !== editBaseSnapshot) editDrafts.set(editDraftKey, { form: { ...editForm }, base: editBaseSnapshot })
  else editDrafts.delete(editDraftKey)
}
watch(editDialogVisible, visible => { if (!visible) cacheEditDraft() }, { flush: 'sync' })
const inspectorDraft = reactive({
  id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual',
  validFrom: '', validTo: '', expiresAt: '',
})
const rebuildIndexLoading = ref(false)
let activeRebuildJobId = ''
let rebuildMonitorSequence = 0
const lastObservedRebuildJob = ref<MemoryIndexRebuildJob | null>(null)
const rebuildMonitorError = ref('')
const indexStatusRefreshing = ref(false)
const displayedRebuildJob = computed(() => indexStatus.value?.job ?? (lastObservedRebuildJob.value && ['cancelled', 'failed', 'interrupted', 'completed'].includes(lastObservedRebuildJob.value.state) ? lastObservedRebuildJob.value : null))
let indexStatusSequence = 0
let memoryPanelDisposed = false
let memoryPanelActive = false
let memoryReadsActive = false
let memoryRefreshSequence = 0
const memoryRefreshing = ref(false)
const canReadMemory = () => !memoryPanelDisposed && memoryPanelActive && !document.hidden
const batchActionLoading = ref(false)
const workspaceScopeSaving = ref(false)
const exportLoading = ref(false)
const importLoading = ref(false)
const importReport = ref<MemoryImportResult | null>(null)
const importTargetLabel = ref('')
const exportReport = ref('')
const deletePreview = ref<MemoryDeletePreview | null>(null)
const memoryImportInput = ref<HTMLInputElement | null>(null)
const inspectorDraftSaving = ref(false)
const forgettingDocIds = ref(new Set<string>())
const restoringDocIds = ref(new Set<string>())
const removingDocIds = ref(new Set<string>())
const batchDeleteProgress = reactive({ active: false, total: 0, done: 0 })
const deletePreflightLoading = ref(false)
const deleteConfirmationOpen = ref(false)
const deletePreflightError = ref('')
const batchContext = ref('')
const batchResults = ref<Array<{ id: string; status: 'success' | 'failed' | 'skipped' | 'pending'; detail: string }>>([])
const deletionReport = ref<{ message: string; warning: boolean } | null>(null)
const feedbackPendingIds = ref(new Set<string>())
const feedbackById = ref<Record<string, string>>({})
const feedbackErrors = ref<Record<string, string>>({})
const maintenancePreview = ref<MemoryMaintenancePreview | null>(null)
const maintenancePreviewPolicyKey = ref('')
const maintenancePreviewLoading = ref(false)
const maintenanceApplyLoading = ref(false)
const maintenanceSaving = ref(false)
const maintenancePolicy = reactive({
  workingRetentionDays: activeWorkspace.value.context.memoryPolicy?.workingRetentionDays ?? 14,
  lowQualityThreshold: activeWorkspace.value.context.memoryPolicy?.lowQualityThreshold ?? 0.55,
  includeStaleWorking: activeWorkspace.value.context.memoryPolicy?.includeStaleWorking !== false,
  includeLowQuality: activeWorkspace.value.context.memoryPolicy?.includeLowQuality !== false,
  includeExactDuplicates: activeWorkspace.value.context.memoryPolicy?.includeExactDuplicates !== false,
})
const hydrateMaintenancePolicy = () => {
  const policy = activeWorkspace.value.context.memoryPolicy
  maintenancePolicy.workingRetentionDays = policy?.workingRetentionDays ?? 14
  maintenancePolicy.lowQualityThreshold = policy?.lowQualityThreshold ?? 0.55
  maintenancePolicy.includeStaleWorking = policy?.includeStaleWorking !== false
  maintenancePolicy.includeLowQuality = policy?.includeLowQuality !== false
  maintenancePolicy.includeExactDuplicates = policy?.includeExactDuplicates !== false
}
const DOC_RENDER_BATCH_SIZE = 80
const visibleDocLimit = ref(DOC_RENDER_BATCH_SIZE)

const layers = computed(() => [
  { value: 'profile', label: t('memoryPanel.layerProfileLabel'), desc: t('memoryPanel.layerProfileDesc'), color: 'purple' },
  { value: 'working', label: t('memoryPanel.layerWorkingLabel'), desc: t('memoryPanel.layerWorkingDesc'), color: 'blue' },
  { value: 'episodic', label: t('memoryPanel.layerEpisodicLabel'), desc: t('memoryPanel.layerEpisodicDesc'), color: 'amber' },
  { value: 'relationship', label: t('memoryPanel.layerRelationshipLabel'), desc: t('memoryPanel.layerRelationshipDesc'), color: 'pink' },
  { value: 'reflective', label: t('memoryPanel.layerReflectiveLabel'), desc: t('memoryPanel.layerReflectiveDesc'), color: 'emerald' },
  { value: 'semantic', label: t('memoryPanel.layerSemanticLabel'), desc: t('memoryPanel.layerSemanticDesc'), color: 'slate' },
])

const memoryScopeOptions = computed<Array<{ value: MemoryScope; label: string }>>(() => [
  { value: 'global', label: t('memoryPanel.scopeGlobal') },
  { value: 'workspace', label: t('memoryPanel.scopeWorkspace') },
  { value: 'session', label: t('memoryPanel.scopeSession') },
])
const memorySourceOptions = computed(() => [
  { value: 'manual', label: t('memoryPanel.sourceManual') },
  { value: 'session', label: t('memoryPanel.sourceSession') },
  { value: 'relationship', label: t('memoryPanel.sourceRelationship') },
  { value: 'reflection', label: t('memoryPanel.sourceReflection') },
  { value: 'import', label: t('memoryPanel.sourceImport') },
  { value: 'profile', label: t('memoryPanel.sourceProfile') },
])

const docViewOptions = computed<Array<{ value: DocViewMode; label: string }>>(() => [
  { value: 'all', label: t('memoryPanel.viewAll') },
  { value: 'recallable', label: t('memoryPanel.viewRecallable') },
  { value: 'review', label: t('memoryPanel.viewReview') },
  { value: 'important', label: t('memoryPanel.viewImportant') },
  { value: 'hits', label: t('memoryPanel.viewHits') },
])

const layerTagType = (layer?: string) => {
  const map: Record<string, TagType> = { profile: 'warning', working: 'primary', episodic: 'info', relationship: 'danger', reflective: 'success', semantic: 'info' }
  return map[layer || ''] || 'info'
}

const formatScore = (value?: number | null) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '-'
const formatLatency = (value?: number | null) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} ms` : '-'

const scorePercent = (value?: number | null) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(Math.min(1, Math.max(0, number)) * 100)}%`
}

const qualityPercent = (doc: MemoryDoc) => scorePercent(doc.quality_score ?? doc.confidence)

const compactText = (text?: string | null, limit = 120) => {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  return `${normalized.slice(0, Math.max(0, limit - 1))}…`
}

const docUpdatedLabel = (doc: MemoryDoc) => {
  const raw = doc.updated_at || (typeof doc.metadata?.timestamp === 'string' ? doc.metadata.timestamp : '')
  if (!raw) return t('memoryPanel.updatedUnknown')
  return String(raw).replace('T', ' ').slice(0, 16)
}

const stringMeta = (doc: MemoryDoc, key: string) => {
  const value = doc.metadata?.[key]
  return typeof value === 'string' && value.trim() ? value : ''
}

const docScopeValue = (doc: MemoryDoc) => stringMeta(doc, 'scope') || currentMemoryScope.value
const docWorkspaceId = (doc: MemoryDoc) => stringMeta(doc, 'workspace_id') || activeWorkspace.value?.id
const docSessionId = (doc: MemoryDoc) => stringMeta(doc, 'session_id') || (docScopeValue(doc) === 'session' ? sessionStore.activeSession?.id : undefined)

const scopeLabel = (scope?: string | null) => {
  const map: Record<string, string> = {
    global: t('memoryPanel.scopeGlobalWorkspace'),
    workspace: t('memoryPanel.scopeWorkspace'),
    session: t('memoryPanel.scopeSession'),
  }
  return map[String(scope || '')] || String(scope || t('memoryPanel.scopeWorkspace'))
}

const maintenancePayload = (): MemoryMaintenancePolicyPayload => ({
  scope: currentMemoryScope.value,
  workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value.id,
  session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
  working_retention_days: maintenancePolicy.workingRetentionDays,
  low_quality_threshold: maintenancePolicy.lowQualityThreshold,
  include_stale_working: maintenancePolicy.includeStaleWorking,
  include_low_quality: maintenancePolicy.includeLowQuality,
  include_exact_duplicates: maintenancePolicy.includeExactDuplicates,
})
const maintenancePolicyKey = () => JSON.stringify(maintenancePayload())
const maintenancePreviewMatchesPolicy = computed(() => Boolean(
  maintenancePreview.value && maintenancePreviewPolicyKey.value === maintenancePolicyKey(),
))

const maintenanceReasonLabel = (reasons: string[]) => reasons.map((reason) => ({
  stale_working: t('memoryPanel.maintenanceStaleWorking'),
  low_quality: t('memoryPanel.maintenanceLowQuality'),
  exact_duplicate: t('memoryPanel.maintenanceExactDuplicate'),
}[reason] || reason)).join(t('memoryPanel.enumerationSeparator'))

const saveMemoryPolicy = async () => {
  if (maintenanceSaving.value) return
  maintenanceSaving.value = true
  try {
    workspaceStore.updateWorkspaceContext(activeWorkspace.value.id, {
      memoryPolicy: {
        workingRetentionDays: maintenancePolicy.workingRetentionDays,
        lowQualityThreshold: maintenancePolicy.lowQualityThreshold,
        includeStaleWorking: maintenancePolicy.includeStaleWorking,
        includeLowQuality: maintenancePolicy.includeLowQuality,
        includeExactDuplicates: maintenancePolicy.includeExactDuplicates,
      },
    })
    ElMessage.success(t('memoryPanel.maintenanceSaved'))
  } finally {
    maintenanceSaving.value = false
  }
}

const previewMemoryMaintenance = async () => {
  if (maintenancePreviewLoading.value || maintenanceApplyLoading.value) return
  maintenancePreviewLoading.value = true
  try {
    const payload = maintenancePayload()
    const key = JSON.stringify(payload)
    const result = await memoryClient.previewMaintenance(payload)
    if (key !== maintenancePolicyKey()) return
    maintenancePreview.value = result
    maintenancePreviewPolicyKey.value = key
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.maintenancePreviewFailed')))
  } finally {
    maintenancePreviewLoading.value = false
  }
}

const reportMemoryDeletion = (result: unknown, authorityMessage: string) => {
  const warning = memoryIndexCleanupStatus(result) !== 'complete'
  const message = memoryDeletionResultText(result, authorityMessage)
  deletionReport.value = { message, warning }
  if (warning) ElMessage.warning(message)
  else ElMessage.success(message)
}
const refreshAfterDeletion = async (authorityConfirmed = true) => {
  try { await refreshMemoryState() }
  catch (error) {
    ElMessage.warning((authorityConfirmed
      ? memoryText('权威删除结果已保留；列表刷新失败：', 'Authority deletion result preserved; list refresh failed: ')
      : memoryText('列表刷新失败：', 'List refresh failed: ')) + describeFailure(error, t('memoryPanel.docDeleteFailed')))
  }
}

const applyMemoryMaintenance = async () => {
  if (maintenanceApplyLoading.value || deleteConfirmationOpen.value || deletePreflightLoading.value || batchActionLoading.value || removingDocIds.value.size) return
  if (!maintenancePreviewMatchesPolicy.value) {
    ElMessage.warning(t('memoryPanel.maintenancePolicyChanged'))
    return
  }
  const payload = maintenancePayload()
  const policyKey = maintenancePolicyKey()
  const previewToken = maintenancePreview.value?.preview_token
  if (!previewToken) {
    ElMessage.warning(t('memoryPanel.maintenancePreviewStale'))
    return
  }
  deleteConfirmationOpen.value = true
  try {
    await ElMessageBox.confirm(
      t('memoryPanel.maintenanceDeleteConfirmMessage', { count: maintenancePreview.value?.summary.delete_count ?? 0 }) + ' · ' + memoryDeletionNote(),
      t('memoryPanel.maintenanceDeleteConfirmTitle'),
      { confirmButtonText: t('memoryPanel.permanentDelete'), cancelButtonText: t('memoryPanel.cancel'), type: 'warning' },
    )
  } catch {
    return
  } finally {
    deleteConfirmationOpen.value = false
  }
  if (memoryPanelDisposed || policyKey !== maintenancePolicyKey() || previewToken !== maintenancePreview.value?.preview_token) return
  maintenanceApplyLoading.value = true
  invalidateReads()
  try {
    const result = await memoryClient.applyMaintenance({
      ...payload,
      preview_token: previewToken,
      confirmation: 'PERMANENT_DELETE',
    })
    reportMemoryDeletion(result, t('memoryPanel.maintenanceDeleted', { count: result.changed_count }))
    maintenancePreview.value = null
    maintenancePreviewPolicyKey.value = ''
    await refreshAfterDeletion()
    try {
      const nextPayload = maintenancePayload()
      const nextKey = JSON.stringify(nextPayload)
      const preview = await memoryClient.previewMaintenance(nextPayload)
      if (nextKey === maintenancePolicyKey()) {
        maintenancePreview.value = preview
        maintenancePreviewPolicyKey.value = nextKey
      }
    } catch {
      maintenancePreview.value = null
      maintenancePreviewPolicyKey.value = ''
      ElMessage.warning(t('memoryPanel.maintenanceRefreshFailed'))
    }
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.maintenanceApplyFailed')))
  } finally {
    maintenanceApplyLoading.value = false
  }
}

const updateDefaultMemoryScope = async (value: string) => {
  const nextScope = normalizeMemoryScope(value)
  const workspaceId = activeWorkspace.value?.id
  if (!workspaceId || workspaceScopeSaving.value || nextScope === currentMemoryScope.value) return
  workspaceScopeSaving.value = true
  try {
    await workspaceStore.updateWorkspaceRemote(workspaceId, { memory_scope: nextScope })
    queryForm.scope = nextScope
    ElMessage.success(t('memoryPanel.scopeSaved'))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.scopeSaveFailed')))
  } finally {
    workspaceScopeSaving.value = false
  }
}


const layerStats = computed(() => layers.value.map(layer => ({
  ...layer,
  count: overview.value?.by_layer[layer.value] ?? docs.value.filter(doc => doc.layer === layer.value).length,
})))
const queryTrace = computed(() => queryResult.value?.trace ?? null)
const queryHitIds = computed(() => new Set([
  ...(queryTrace.value?.selected_ids ?? []),
  ...((queryResult.value?.results ?? []).map(item => item.id).filter(Boolean)),
]))

const reviewDocs = computed(() => reviewCandidates.value.slice().sort((left, right) => {
  const leftScore = Math.min(Number(left.confidence ?? 1), Number(left.quality_score ?? 1))
  const rightScore = Math.min(Number(right.confidence ?? 1), Number(right.quality_score ?? 1))
  return leftScore - rightScore
}))
const memoryTabs = computed(() => [
  { value: 'library' as const, label: t('memoryPanel.tabLibrary'), count: docs.value.length, icon: Collection },
  { value: 'review' as const, label: t('memoryPanel.tabReview'), count: reviewDocs.value.length, icon: User },
  { value: 'overview' as const, label: t('memoryPanel.tabOverview'), icon: DataAnalysis },
])


const onMemoryTabKeydown = (event: KeyboardEvent, index: number) => {
  const key = event.key
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(key)) return
  event.preventDefault()
  const tabs = memoryTabs.value
  const nextIndex = key === 'Home'
    ? 0
    : key === 'End'
      ? tabs.length - 1
      : (index + (key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  activeTab.value = tabs[nextIndex].value
  void nextTick(() => document.getElementById(`memory-tab-${tabs[nextIndex].value}`)?.focus())
}

const indexUiStatus = computed(() => getMemoryIndexUiStatus(indexStatus.value, docsRequest.loading))
const indexStatusLabel = computed(() => indexUiStatus.value.label)
const indexAvailabilityLabel = computed(() => indexUiStatus.value.availabilityLabel)
const indexStatusTone = computed<TagType>(() => indexUiStatus.value.tone)

const querySummary = computed(() => {
  const results = queryResult.value?.results ?? []
  if (!results.length) return ''
  const best = Math.max(...results.map(item => Number(item.score ?? 0)))
  return t('memoryPanel.querySummary', { count: results.length, score: best.toFixed(4) })
})

const defaultQueryLayers = ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic']
const effectiveQueryLayers = computed(() => {
  if (selectedQueryLayers.value.length) return selectedQueryLayers.value
  return defaultQueryLayers
})

const filterReasonText = computed(() => {
  const reasons = queryTrace.value?.filter_reasons ?? {}
  return Object.entries(reasons)
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${reason} ${count}`)
    .join(' · ')
})

const openLayerInLibrary = (layer: string) => {
  filterLayer.value = filterLayer.value === layer ? '' : layer
  activeTab.value = 'library'
}

const selectDocFromAdvanced = (id: string) => {
  if (!docs.value.some(doc => doc.id === id)) {
    ElMessage.warning(memoryText('此结果不在当前资料库范围，请先切换到结果所属范围再查看。', 'This result is outside the current library. Switch to its scope to inspect it.'))
    return
  }
  selectDocById(id)
  advancedToolsVisible.value = false
  activeTab.value = 'library'
}

const resetDocFilters = () => {
  docViewMode.value = 'all'
  docSortMode.value = 'updated'
  filterLayer.value = ''
  searchText.value = ''
}

const docMatchesView = (doc: MemoryDoc, mode: DocViewMode) => {
  if (mode === 'recallable') return doc.state === 'active' && doc.index_status !== 'excluded'
  if (mode === 'review') return reviewDocs.value.some(item => item.id === doc.id)
  if (mode === 'important') return Number(doc.importance ?? 0) >= 0.8
  if (mode === 'hits') return queryHitIds.value.has(doc.id)
  return true
}

const docViewCount = (mode: DocViewMode) => docs.value.filter(doc => docMatchesView(doc, mode)).length

const docTimestampValue = (doc: MemoryDoc) => {
  const raw = doc.updated_at || (typeof doc.metadata?.timestamp === 'string' ? doc.metadata.timestamp : '')
  const value = raw ? Date.parse(raw) : 0
  return Number.isFinite(value) ? value : 0
}

const docSortValue = (doc: MemoryDoc, mode: DocSortMode) => {
  if (mode === 'importance') return Number(doc.importance ?? 0)
  if (mode === 'quality') return Number(doc.quality_score ?? 0)
  if (mode === 'confidence') return Number(doc.confidence ?? 0)
  return docTimestampValue(doc)
}

const filteredDocs = computed(() => {
  const options = scopedDocOptions()
  if (docsScopeKey.value !== JSON.stringify([options.scope, options.workspaceId, options.sessionId])) return []
  let list: MemoryDoc[] = docs.value
  list = list.filter(d => docMatchesView(d, docViewMode.value))
  if (filterLayer.value) list = list.filter(d => d.layer === filterLayer.value)
  if (searchText.value.trim()) {
    const q = searchText.value.toLowerCase()
    list = list.filter(d => [
      d.id,
      d.text,
      d.type,
      d.layer,
      typeof d.metadata?.source === 'string' ? d.metadata.source : '',
    ].join(' ').toLowerCase().includes(q))
  }
  return [...list].sort((left, right) => docSortValue(right, docSortMode.value) - docSortValue(left, docSortMode.value))
})

const visibleDocs = computed(() => filteredDocs.value.slice(0, visibleDocLimit.value))
const remainingFilteredDocCount = computed(() => Math.max(0, filteredDocs.value.length - visibleDocs.value.length))
const selectedDoc = computed(() => filteredDocs.value.find(doc => doc.id === selectedDocId.value) || filteredDocs.value[0] || null)
watch(
  () => [
    selectedDoc.value,
    currentMemoryScope.value,
    activeWorkspace.value.id,
    sessionStore.activeSession?.id,
  ] as const,
  ([doc, scope, workspaceId, sessionId]) => {
    if (!doc) {
    operationsRequest.reset()
    return
    }
    void loadOperations(doc.id, {
      scope,
      workspaceId: scope === 'global' ? undefined : workspaceId,
      sessionId: scope === 'session' ? sessionId : undefined,
    })
  },
  { immediate: true },
)
const hasDocFilters = computed(() => docViewMode.value !== 'all' || docSortMode.value !== 'updated' || Boolean(filterLayer.value) || Boolean(searchText.value.trim()))
const batchTargetDocs = computed(() => hasDocFilters.value ? filteredDocs.value : [])
const batchTargetCount = computed(() => batchTargetDocs.value.length)
const batchActionDisabled = computed(() => deletePreflightLoading.value || batchActionLoading.value || !hasDocFilters.value || batchTargetCount.value === 0)
const batchDeleteLabel = computed(() => {
  if (batchDeleteProgress.active) return t('memoryPanel.batchDeleting', { done: batchDeleteProgress.done, total: batchDeleteProgress.total })
  if (!hasDocFilters.value) return t('memoryPanel.batchDeleteNeedFilters')
  return t('memoryPanel.batchDeleteFilteredLabel', { count: batchTargetCount.value })
})

const showMoreDocs = () => {
  visibleDocLimit.value += DOC_RENDER_BATCH_SIZE
}

const selectDoc = (doc: MemoryDoc) => {
  selectedDocId.value = doc.id
}

const selectDocById = (id: string) => {
  selectedDocId.value = id
  const doc = docs.value.find(item => item.id === id)
  if (!doc) return
  if (docViewMode.value !== 'all' && !docMatchesView(doc, docViewMode.value)) docViewMode.value = 'all'
  if (filterLayer.value && doc.layer !== filterLayer.value) filterLayer.value = ''
  if (searchText.value.trim() && !filteredDocs.value.some(item => item.id === id)) searchText.value = ''
  const visibleIndex = filteredDocs.value.findIndex(item => item.id === id)
  if (visibleIndex >= visibleDocLimit.value) visibleDocLimit.value = visibleIndex + 1
}

const isQueryHit = (doc: MemoryDoc) => queryHitIds.value.has(doc.id)

const toggleQueryLayer = (layer: string) => {
  const set = new Set(effectiveQueryLayers.value)
  if (set.has(layer)) {
    if (set.size === 1) return
    set.delete(layer)
  } else {
    set.add(layer)
  }
  selectedQueryLayers.value = [...set]
}

const resetQueryLayers = () => {
  selectedQueryLayers.value = []
}

const rollbackMemoryDoc = async (doc: MemoryDoc, revision: number) => {
  const result = await memoryClient.rollbackDoc(doc.id, revision, docSessionId(doc))
  if (result?.status === 'rolled_back' || result?.status === 'updated' || result?.status === 'ok') {
    ElMessage.success(t('memoryPanel.rollbackSuccess', { revision }))
    selectedDocId.value = doc.id
    await refreshMemoryState()
  }
}

provide(memoryInspectorActionsKey, { rollback: rollbackMemoryDoc })

const setDocRemoving = (id: string, removing: boolean) => {
  const next = new Set(removingDocIds.value)
  if (removing) {
    next.add(id)
  } else {
    next.delete(id)
  }
  removingDocIds.value = next
}

const setPendingDocId = (target: typeof forgettingDocIds | typeof restoringDocIds, id: string, pending: boolean) => {
  const next = new Set(target.value)
  if (pending) next.add(id)
  else next.delete(id)
  target.value = next
}


const loadScopedDocs = () => loadDocs(scopedDocOptions())

const refreshIndexStatus = async () => {
  if (!canReadMemory()) return
  const sequence = ++indexStatusSequence
  try {
    const result = await memoryClient.getIndexStatus()
    if (!canReadMemory() || sequence !== indexStatusSequence) return
    indexStatus.value = result
    const job = indexStatus.value.job
    if (job) {
      lastObservedRebuildJob.value = job
      rebuildMonitorError.value = ''
    } else if (lastObservedRebuildJob.value && !rebuildTerminalStates.has(lastObservedRebuildJob.value.state)) {
      rebuildMonitorError.value = memoryText('当前服务未找到此前的重建任务，终态未知。可以重新发起重建。', 'The service no longer has the previous rebuild job. Its final state is unknown. A new rebuild can be started.')
      activeRebuildJobId = ''
      rebuildMonitorSequence += 1
      rebuildIndexLoading.value = false
    }
    if (job && !rebuildTerminalStates.has(job.state)) {
      rebuildIndexLoading.value = true
      if (activeRebuildJobId !== job.job_id) void monitorMemoryIndexRebuild(job.job_id, false)
    } else {
      stopRebuildMonitoring()
      rebuildIndexLoading.value = false
    }
  } catch (error) {
    if (!canReadMemory() || sequence !== indexStatusSequence) return
    const message = describeFailure(error, t('memoryPanel.indexStatusReadFailed'))
    indexStatus.value = {
      status: 'error',
      count: docs.value.length,
      backend: 'unavailable',
      healthy: false,
      message,
      metadata: { index_healthy: false, index_dirty: true, degraded: true },
    }
    throw error
  }
}

const checkMemoryIndexStatus = async () => {
  if (indexStatusRefreshing.value) return
  indexStatusRefreshing.value = true
  try { await refreshIndexStatus() }
  catch (error) { ElMessage.error(describeFailure(error, t('memoryPanel.indexStatusReadFailed'))) }
  finally { indexStatusRefreshing.value = false }
}

const refreshMemoryState = async () => {
  if (!canReadMemory()) return
  const sequence = ++memoryRefreshSequence
  const context = memoryContextKey()
  const isCurrent = () => canReadMemory() && sequence === memoryRefreshSequence && context === memoryContextKey()
  memoryRefreshing.value = true
  // Reset request sequences, keeping the cached rows and scoped dirty drafts.
  invalidateReads()
  const options = scopedDocOptions()
  try {
    await Promise.all([
      loadDocs(options),
      loadOverview(options),
      loadForgottenDocs(options),
      loadCandidates(options),
    ])
    if (!isCurrent()) return
    try {
      await refreshIndexStatus()
    } catch (error) {
      console.debug('[MemoryPanel] failed to refresh index status:', error)
    }
  } finally {
    if (isCurrent()) {
      memoryRefreshing.value = false
      openRequestedMemoryDoc()
    }
  }
}

const handleAdvancedToolCommand = (command: string) => {
  if (command === 'open-index') advancedToolsVisible.value = true
  if (command === 'export') void exportMemory()
  if (command === 'import') memoryImportInput.value?.click()
}

const exportMemory = async () => {
  if (exportLoading.value) return
  exportLoading.value = true
  const options = scopedDocOptions()
  try {
    const payload = await memoryClient.exportDocs({ ...options, includeState: 'all' })
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `yuizaki-memory-${options.scope}-${encodeURIComponent(options.sessionId || options.workspaceId || 'global')}-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
    exportReport.value = t('memoryPanel.exportSuccess', { count: payload.count }) + ' · ' + [payload.scope, payload.workspace_id, payload.session_id].filter(Boolean).join(' / ')
    ElMessage.success(exportReport.value)
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.exportFailed')))
  } finally {
    exportLoading.value = false
  }
}

const handleMemoryImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || importLoading.value) return
  const options = scopedDocOptions()
  const context = memoryContextKey()
  importLoading.value = true
  importReport.value = null
  try {
    if (file.size > 10 * 1024 * 1024) throw new Error(t('memoryPanel.importTooLarge'))
    const parsed: unknown = JSON.parse(await file.text())
    if (!parsed || typeof parsed !== 'object') throw new Error(t('memoryPanel.importInvalidJson'))
    const envelope = parsed as { format?: unknown; version?: unknown; docs?: unknown }
    if (envelope.format !== 'yuizaki-memory-export' || envelope.version !== 1 || !Array.isArray(envelope.docs)) {
      throw new Error(t('memoryPanel.importUnsupportedFormat'))
    }
    const importDocs = envelope.docs.filter((item): item is { id?: string; text: string; metadata?: Record<string, unknown> } => {
      if (!item || typeof item !== 'object') return false
      const candidate = item as { id?: unknown; text?: unknown; metadata?: unknown }
      return typeof candidate.text === 'string' && candidate.text.trim().length > 0
        && (candidate.id === undefined || typeof candidate.id === 'string')
        && (candidate.metadata === undefined || (candidate.metadata !== null && typeof candidate.metadata === 'object' && !Array.isArray(candidate.metadata)))
    })
    if (importDocs.length !== envelope.docs.length) throw new Error(memoryText('备份中包含无效记录，尚未导入。请检查正文、ID和metadata格式。', 'The backup contains invalid records. Nothing was imported. Check text, IDs and metadata.'))
    if (!importDocs.length) throw new Error(t('memoryPanel.importEmpty'))
    if (context !== memoryContextKey() || memoryPanelDisposed) return
    const targetLabel = [options.scope, options.workspaceId, options.sessionId].filter(Boolean).join(' / ')
    const existingIds = new Set(docs.value.map(doc => doc.id))
    const duplicateCount = importDocs.filter(doc => doc.id && existingIds.has(doc.id)).length
    await ElMessageBox.confirm(
      t('memoryPanel.importConfirmMessage', {
        count: importDocs.length,
        scope: scopeLabel(options.scope) + ' · ' + targetLabel,
        note: (duplicateCount ? t('memoryPanel.importConfirmNote', { count: duplicateCount }) + ' · ' : '') + memoryText('备份原范围将重新映射到此目标范围；保留软遗忘状态。', 'The backup scope will be remapped to this target scope; soft-forgotten state is preserved.'),
      }),
      t('memoryPanel.importConfirmTitle'),
      { confirmButtonText: t('memoryPanel.importStart'), cancelButtonText: t('memoryPanel.cancel'), type: 'info' },
    )
    if (context !== memoryContextKey() || memoryPanelDisposed) return
    invalidateReads()
    const result = await memoryClient.importDocs({
      format: 'yuizaki-memory-export',
      version: 1,
      docs: importDocs.map(doc => ({ id: doc.id, text: doc.text, metadata: doc.metadata })),
      scope: options.scope,
      workspace_id: options.scope === 'global' ? undefined : options.workspaceId,
      session_id: options.sessionId,
      conflict: 'skip',
    })
    if (context === memoryContextKey() && !memoryPanelDisposed) {
      importReport.value = result
      importTargetLabel.value = targetLabel
    }
    ElMessage.success(t('memoryPanel.importSuccess', { imported: result.imported_count, skipped: result.skipped_count }))
    await refreshMemoryState()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close' && !(error instanceof Error && error.message === 'cancel')) {
      ElMessage.error(describeFailure(error, t('memoryPanel.importFailed')))
    }
  } finally {
    input.value = ''
    importLoading.value = false
  }
}

const importReasonLabel = (reason: string) => ({
  id_exists: t('memoryPanel.importReasonIdExists'),
  terminal_or_review_candidate: t('memoryPanel.importReasonTerminal'),
  write_failed: t('memoryPanel.importReasonWriteFailed'),
  restore_state_failed: t('memoryPanel.importReasonRestoreFailed'),
}[reason] || reason)

const decideReviewCandidate = async ({ doc, decision }: { doc: MemoryDoc; decision: 'approve' | 'reject' }) => {
  if (reviewProcessingId.value) return
  reviewProcessingId.value = doc.id
  try {
    await reviewCandidate(doc.id, decision, decision === 'approve' ? 'user_approved' : 'user_rejected', docSessionId(doc))
    ElMessage.success(decision === 'approve' ? t('memoryPanel.reviewKept') : t('memoryPanel.reviewRejected'))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.reviewFailed')))
  } finally {
    reviewProcessingId.value = ''
  }
}

const rebuildTerminalStates = new Set<MemoryIndexRebuildJob['state']>(['cancelled', 'failed', 'interrupted', 'completed'])
let rebuildPollTimer: ReturnType<typeof window.setTimeout> | null = null
let finishRebuildWait: (() => void) | null = null
const waitForRebuildPoll = () => new Promise<void>(resolve => {
  finishRebuildWait = resolve
  rebuildPollTimer = window.setTimeout(() => {
    rebuildPollTimer = null
    finishRebuildWait = null
    resolve()
  }, 500)
})
const stopRebuildMonitoring = () => {
  rebuildMonitorSequence += 1
  activeRebuildJobId = ''
  rebuildIndexLoading.value = false
  if (rebuildPollTimer !== null) window.clearTimeout(rebuildPollTimer)
  rebuildPollTimer = null
  finishRebuildWait?.()
  finishRebuildWait = null
}

const projectRebuildJob = (job: MemoryIndexRebuildJob, indexState: string) => {
  if (memoryPanelDisposed) return
  const previous = lastObservedRebuildJob.value
  if (previous?.job_id === job.job_id) {
    if (rebuildTerminalStates.has(previous.state) && !rebuildTerminalStates.has(job.state)) return
    if (Date.parse(previous.updated_at) > Date.parse(job.updated_at)) return
  }
  indexStatusSequence += 1
  lastObservedRebuildJob.value = job
  const current = indexStatus.value
  indexStatus.value = {
    status: indexState,
    count: current?.count ?? docs.value.length,
    backend: current?.backend,
    healthy: current?.healthy,
    message: current?.message,
    metadata: current?.metadata,
    job,
  }
}

const monitorMemoryIndexRebuild = async (jobId: string, announceCompletion: boolean) => {
  if (!canReadMemory() || activeRebuildJobId === jobId) return
  stopRebuildMonitoring()
  const monitorSequence = ++rebuildMonitorSequence
  activeRebuildJobId = jobId
  rebuildIndexLoading.value = true
  rebuildMonitorError.value = ''
  let polls = 0
  try {
    while (canReadMemory() && activeRebuildJobId === jobId && monitorSequence === rebuildMonitorSequence) {
      if (++polls > 240) throw new Error(memoryText('已停止自动跟踪，重建终态未知；刷新状态以继续核对。', 'Automatic tracking stopped; final rebuild state unknown. Refresh status to check again.'))
      const response = await memoryClient.getIndexRebuildJob(jobId)
      if (!canReadMemory() || activeRebuildJobId !== jobId || monitorSequence !== rebuildMonitorSequence) return
      projectRebuildJob(response.job, response.index_status)
      const observed = lastObservedRebuildJob.value
      const job = observed?.job_id === jobId ? observed : response.job
      if (rebuildTerminalStates.has(job.state)) {
        if (job.state === 'completed') {
          const indexedCount = Number(job.result?.indexed_count ?? job.processed_count)
          if (announceCompletion) ElMessage.success(t('memoryPanel.indexRebuilt', { count: indexedCount }))
          await refreshMemoryState()
        } else if (job.state === 'cancelled') {
          if (announceCompletion) ElMessage.info(t('memoryPanel.indexRebuildCancelled'))
          await refreshIndexStatus()
        } else if (announceCompletion) {
          ElMessage.error(job.last_error || t('memoryPanel.indexRebuildFailedRetry'))
        }
        break
      }
      await waitForRebuildPoll()
    }
  } catch (error) {
    if (canReadMemory() && activeRebuildJobId === jobId && monitorSequence === rebuildMonitorSequence) {
      rebuildMonitorError.value = describeFailure(error, t('memoryPanel.indexRebuildProgressFailed'))
      // A backend restart can discard the in-memory job; refresh once so stale
      // progress is not left looking active and the authority status is visible.
      if (error instanceof Error && /404|not found/i.test(error.message)) {
        await refreshIndexStatus().catch(() => undefined)
      } else {
        ElMessage.error(describeFailure(error, t('memoryPanel.indexRebuildProgressFailed')))
      }
    }
  } finally {
    if (activeRebuildJobId === jobId && monitorSequence === rebuildMonitorSequence) {
      activeRebuildJobId = ''
      rebuildIndexLoading.value = false
    }
  }
}

const rebuildMemoryIndex = async () => {
  if (rebuildIndexLoading.value) return
  rebuildIndexLoading.value = true
  try {
    const previousJob = indexStatus.value?.job
    const response = previousJob?.recoverable && rebuildTerminalStates.has(previousJob.state)
      ? await memoryClient.retryIndexRebuild(previousJob.job_id)
      : await memoryClient.rebuildIndex()
    if (memoryPanelDisposed) return
    projectRebuildJob(response.job, response.index_status)
    await monitorMemoryIndexRebuild(response.job.job_id, true)
  } catch (error) {
    rebuildIndexLoading.value = false
    rebuildMonitorError.value = describeFailure(error, t('memoryPanel.indexRebuildFailed'))
    ElMessage.error(rebuildMonitorError.value)
  }
}

const cancelMemoryIndexRebuild = async () => {
  const job = indexStatus.value?.job
  if (!job || !['queued', 'running', 'cancelling'].includes(job.state)) return
  try {
    const response = await memoryClient.cancelIndexRebuild(job.job_id)
    if (memoryPanelDisposed || displayedRebuildJob.value?.job_id !== job.job_id) return
    projectRebuildJob(response.job, response.index_status)
    if (!activeRebuildJobId) {
      rebuildIndexLoading.value = true
      void monitorMemoryIndexRebuild(job.job_id, false)
    }
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.indexRebuildCancelFailed')))
  }
}

const parseJsonObject = (rawValue: string, label: string) => {
  const raw = rawValue.trim()
  if (!raw) return {}
  const parsed: unknown = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(t('memoryPanel.jsonObjectRequired', { label }))
  }
  return parsed as Record<string, unknown>
}

const submitQuery = async () => {
  if (!queryForm.query.trim() || queryRequest.loading) return
  if (queryForm.scope === 'session' && !sessionStore.activeSession) {
    ElMessage.warning(memoryText('会话范围需要当前会话。', 'Session scope requires an active session.'))
    return
  }
  feedbackById.value = {}
  feedbackErrors.value = {}
  await queryMemory({
    query: queryForm.query.trim(),
    workspace_id: queryForm.scope === 'global' ? undefined : activeWorkspace.value.id,
    top_k: queryForm.top_k,
    session_id: queryForm.scope === 'session' ? sessionStore.activeSession?.id : undefined,
    scope: queryForm.scope,
    layers: selectedQueryLayers.value.length ? effectiveQueryLayers.value : undefined,
    expand_relations: queryForm.expand_relations,
    relation_limit: queryForm.relation_limit,
    relation_depth: queryForm.relation_depth,
  })
}


const handleRecallFeedback = async (payload: { id: string; feedback: 'helpful' | 'not_helpful' | 'incorrect' | 'dismissed' }) => {
  if (feedbackPendingIds.value.has(payload.id)) return
  const query = queryResult.value
  if (!query?.results.some(item => item.id === payload.id)) return
  feedbackPendingIds.value = new Set([...feedbackPendingIds.value, payload.id])
  delete feedbackErrors.value[payload.id]
  try {
    const doc = query.results.find(item => item.id === payload.id)
    const sessionId = typeof doc?.metadata?.session_id === 'string' ? doc.metadata.session_id : query.trace?.session_id
    await recordRecallFeedback(payload.id, payload.feedback, sessionId)
    if (queryResult.value === query) {
      feedbackById.value[payload.id] = payload.feedback
      ElMessage.success(payload.feedback === 'helpful' ? t('memoryPanel.feedbackHelpful') : t('memoryPanel.feedbackRecorded'))
    }
  } catch (error) {
    if (queryResult.value === query) feedbackErrors.value[payload.id] = describeFailure(error, t('memoryPanel.feedbackFailed'))
  } finally {
    const next = new Set(feedbackPendingIds.value)
    next.delete(payload.id)
    feedbackPendingIds.value = next
  }
}

const openEditDoc = (doc: MemoryDoc) => {
  cacheEditDraft()
  editContext = memoryContextKey()
  editDraftKey = editContext + ':' + doc.id
  editTarget.value = JSON.parse(JSON.stringify(doc)) as MemoryDoc
  const form = {
    id: doc.id, text: doc.text || '', type: doc.type || 'fact', layer: doc.layer || 'semantic',
    importance: Number(doc.importance ?? 0.5), confidence: Number(doc.confidence ?? 0.72),
    source: docSourceValue(doc), metadataJson: JSON.stringify(doc.metadata || {}, null, 2),
  }
  const saved = editDrafts.get(editDraftKey)
  Object.assign(editForm, saved?.form ?? form)
  editBaseSnapshot = saved?.base ?? JSON.stringify(form)
  editDialogVisible.value = true
}

let consumedEditRequest = ''
const requestedMemoryDocId = () => {
  const value = Array.isArray(route.query.edit) ? route.query.edit[0] : route.query.edit
  return route.name === 'memory' && typeof value === 'string' ? value.trim() : ''
}
const openRequestedMemoryDoc = () => {
  const requestedId = requestedMemoryDocId()
  if (!requestedId || !canReadMemory() || memoryRefreshing.value || docsRequest.loading || docsRequest.error || !docsRequest.data) return
  if (!hasScopedDocCache.value) return
  // The router can advance before workspace/session stores finish switching.
  if (typeof route.params.workspaceId === 'string' && route.params.workspaceId !== activeWorkspace.value.id) return
  if (typeof route.params.sessionId === 'string' && route.params.sessionId !== sessionStore.activeSession?.id) return
  const requestKey = JSON.stringify([memoryContextKey(), requestedId])
  if (consumedEditRequest === requestKey) return
  consumedEditRequest = requestKey
  const doc = docs.value.find(item => item.id === requestedId)
  if (!doc) {
    ElMessage.warning(t('memoryPanel.docNotFound'))
    return
  }
  selectDocById(requestedId)
  openEditDoc(doc)
}

const buildDocUpdatePayload = (
  doc: MemoryDoc,
  overrides: {
    text?: string
    type?: string
    layer?: string
    importance?: number
    confidence?: number
    confidence_source?: string
    metadata?: Record<string, unknown>
    edit_reason?: string
  },
) => {
  const scope = docScopeValue(doc)
  const confidenceSource = (overrides.confidence_source ?? stringMeta(doc, 'confidence_source')) || undefined
  return {
    text: overrides.text ?? doc.text ?? '',
    type: overrides.type ?? doc.type ?? 'fact',
    layer: overrides.layer ?? doc.layer ?? 'semantic',
    importance: overrides.importance ?? Number(doc.importance ?? 0.5),
    confidence: overrides.confidence ?? Number(doc.confidence ?? 0.72),
    confidence_source: confidenceSource,
    metadata: {
      ...(doc.metadata || {}),
      ...(overrides.metadata || {}),
    },
    scope,
    workspace_id: scope === 'global' ? undefined : docWorkspaceId(doc),
    session_id: scope === 'session' ? docSessionId(doc) : undefined,
    edit_reason: overrides.edit_reason,
  }
}

const updateSelectedDoc = async (
  doc: MemoryDoc,
  overrides: Parameters<typeof buildDocUpdatePayload>[1],
  successMessage: string,
) => {
  if (updateRequest.loading || batchActionLoading.value) return null
  const context = memoryContextKey()
  const selection = selectedDocId.value
  const result = await updateDoc(doc.id, buildDocUpdatePayload(doc, overrides))
  if (result?.status === 'updated' || result?.storage_status === 'saved') {
    if (result.index_status === 'pending' || result.index_status === 'failed') ElMessage.warning(successMessage + ' · ' + memoryIndexLabel(result.index_status))
    else ElMessage.success(successMessage)
    if (context === memoryContextKey() && selection === selectedDocId.value) selectedDocId.value = doc.id
    await refreshMemoryState()
  } else {
    ElMessage.error(updateRequest.error || t('memoryPanel.docUpdateFailed'))
  }
  return result
}

const moveDocLayer = async (doc: MemoryDoc, layer: string) => {
  if (doc.layer === layer) return
  await updateSelectedDoc(
    doc,
    {
      layer,
      metadata: { layer },
      edit_reason: `move_layer:${doc.layer || 'unknown'}->${layer}`,
    },
    t('memoryPanel.movedToLayer', { layer }),
  )
}

const boostDocImportance = async (doc: MemoryDoc) => {
  const nextImportance = Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85))
  await updateSelectedDoc(
    doc,
    {
      importance: nextImportance,
      edit_reason: 'boost_importance',
    },
    t('memoryPanel.importanceBoosted'),
  )
}

const batchUpdateVisibleDocs = async (
  actionLabel: string,
  buildOverrides: (doc: MemoryDoc) => Parameters<typeof buildDocUpdatePayload>[1],
) => {
  if (batchActionLoading.value || deletePreflightLoading.value || deleteConfirmationOpen.value || updateRequest.loading) return
  if (!hasDocFilters.value) { ElMessage.info(t('memoryPanel.batchNeedsFilters')); return }
  const targets = batchTargetDocs.value.map(doc => ({ id: doc.id, payload: buildDocUpdatePayload(doc, buildOverrides(doc)) }))
  if (!targets.length) return
  const context = memoryContextKey()
  batchActionLoading.value = true
  try {
    try {
      await ElMessageBox.confirm(t('memoryPanel.batchConfirmMessage', { count: targets.length, action: actionLabel }),
        t('memoryPanel.batchConfirmTitle'), { confirmButtonText: actionLabel, cancelButtonText: t('memoryPanel.cancel'), type: 'warning' })
    } catch { return }
    if (context !== memoryContextKey() || memoryPanelDisposed) return
    batchResults.value = []
    batchContext.value = context
    for (const target of targets) {
      if (context !== memoryContextKey() || memoryPanelDisposed) break
      try {
        const result = await updateDoc(target.id, target.payload)
        const ok = result?.status === 'updated' || result?.storage_status === 'saved'
        batchResults.value.push({ id: target.id, status: ok ? 'success' : 'failed',
          detail: ok ? memoryIndexLabel(result?.index_status) : updateRequest.error || t('memoryPanel.docUpdateFailed') })
      } catch (error) {
        batchResults.value.push({ id: target.id, status: 'failed', detail: describeFailure(error, t('memoryPanel.docUpdateFailed')) })
      }
    }
    const done = new Set(batchResults.value.map(item => item.id))
    for (const target of targets) if (!done.has(target.id)) batchResults.value.push({ id: target.id, status: 'skipped', detail: memoryText('范围或面板已切换，未执行', 'Scope or panel changed; not executed') })
    if (memoryPanelDisposed) return
    if (batchResults.value.every(item => item.status === 'success')) ElMessage.success(t('memoryPanel.batchProcessed', { count: targets.length }))
    else ElMessage.warning(memoryText('批处理未全部成功，请查看逐项结果。', 'Some items did not succeed. Review the item results.'))
    await refreshMemoryState()
  } finally { batchActionLoading.value = false }
}

const batchBoostVisibleDocs = () => batchUpdateVisibleDocs(t('memoryPanel.batchBoostAction'), doc => ({
  importance: Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85)), edit_reason: 'batch_boost_importance',
}))

// A failed preflight is an error; only dismissing the confirmation is cancellation.
const confirmMemoryDeletion = async (ids: string[], sessionId: string | undefined, title: string, context: string) => {
  if (deletePreflightLoading.value || deleteConfirmationOpen.value) return false
  deletePreflightLoading.value = true
  deletePreflightError.value = ''
  let preview: MemoryDeletePreview
  try {
    preview = await memoryClient.previewDelete(ids, sessionId)
    if (context !== memoryContextKey()) return false
    deletePreview.value = preview
  } catch (error) {
    if (context !== memoryContextKey() || memoryPanelDisposed) return false
    deletePreflightError.value = describeFailure(error, t('memoryPanel.docDeleteFailed'))
    ElMessage.error(deletePreflightError.value)
    return false
  } finally { deletePreflightLoading.value = false }
  deleteConfirmationOpen.value = true
  try {
    await ElMessageBox.confirm(deletePreviewMessage(preview), title, {
      confirmButtonText: t('memoryPanel.permanentDelete'), cancelButtonText: t('memoryPanel.cancel'), type: 'warning',
    })
    return context === memoryContextKey() && !memoryPanelDisposed
  } catch { return false }
  finally { deleteConfirmationOpen.value = false }
}

const batchDeleteVisibleDocs = async () => {
  if (batchActionLoading.value || deletePreflightLoading.value || deleteConfirmationOpen.value || updateRequest.loading) return
  if (!hasDocFilters.value) { ElMessage.info(t('memoryPanel.batchDeleteSelectionRequired')); return }
  const targets = batchTargetDocs.value.map(doc => ({ id: doc.id, sessionId: docSessionId(doc) }))
  if (!targets.length) return
  const context = memoryContextKey()
  const sessionId = scopedDocOptions().sessionId
  batchActionLoading.value = true
  try {
    if (!await confirmMemoryDeletion(targets.map(doc => doc.id), sessionId,
      t('memoryPanel.batchDeleteConfirmTitle', { count: targets.length }), context) || memoryPanelDisposed) return
    batchResults.value = []
    batchContext.value = context
    batchDeleteProgress.active = true
    batchDeleteProgress.total = targets.length
    batchDeleteProgress.done = 0
    invalidateReads()
    for (const doc of targets) {
      if (context !== memoryContextKey() || memoryPanelDisposed) break
      try {
        const result = await memoryClient.removeDoc(doc.id, doc.sessionId)
        batchResults.value.push({ id: doc.id, status: memoryIndexCleanupStatus(result) === 'complete' ? 'success' : 'pending', detail: memoryDeletionResultText(result, t('memoryPanel.docDeleted')) })
        batchDeleteProgress.done += 1
      } catch (error) {
        batchResults.value.push({ id: doc.id, status: 'failed', detail: describeFailure(error, t('memoryPanel.docDeleteFailed')) })
      }
    }
    const done = new Set(batchResults.value.map(item => item.id))
    for (const doc of targets) if (!done.has(doc.id)) batchResults.value.push({ id: doc.id, status: 'skipped', detail: memoryText('范围或面板已切换，未执行', 'Scope or panel changed; not executed') })
    if (memoryPanelDisposed) return
    const complete = batchResults.value.every(item => item.status === 'success')
    const message = t('memoryPanel.batchDeleted', { count: batchDeleteProgress.done }) + (complete ? '' : ' · ' + memoryText('部分条目失败、跳过或索引清理待核对；请查看逐项结果。', 'Some items failed, were skipped or await index cleanup confirmation. Review item results.'))
    deletionReport.value = { message, warning: !complete }
    if (complete) ElMessage.success(message)
    else ElMessage.warning(message)
    await refreshAfterDeletion()
  } finally {
    batchDeleteProgress.active = false
    batchActionLoading.value = false
  }
}

const submitEditDoc = async () => {
  const target = editTarget.value
  if (!target || !editForm.text.trim() || updateRequest.loading || batchActionLoading.value) return
  if (editContext !== memoryContextKey()) {
    ElMessage.warning(memoryText('范围已切换；草稿已保留，请回到原范围保存。', 'Scope changed; draft preserved. Return to the original scope to save.'))
    return
  }
  const key = editDraftKey
  const submitted = { ...editForm }
  const snapshot = JSON.stringify(submitted)
  try {
    const metadata = {
      ...parseJsonObject(submitted.metadataJson, 'Metadata'),
      source: submitted.source, confidence_source: submitted.source,
    }
    const payload = buildDocUpdatePayload(target, {
      text: submitted.text.trim(), type: submitted.type || 'fact', layer: submitted.layer,
      importance: submitted.importance, confidence: submitted.confidence,
      confidence_source: submitted.source, metadata, edit_reason: 'manual_edit',
    })
    const result = await updateDoc(target.id, payload)
    if (result?.status !== 'updated' && result?.storage_status !== 'saved') {
      ElMessage.error(updateRequest.error || t('memoryPanel.docUpdateFailed'))
      return
    }
    const savedForm = { ...submitted, text: submitted.text.trim() }
    const savedSnapshot = JSON.stringify(savedForm)
    const cached = editDrafts.get(key)
    if (cached && JSON.stringify(cached.form) !== snapshot) cached.base = savedSnapshot
    else editDrafts.delete(key)
    if (key === editDraftKey) {
      editBaseSnapshot = savedSnapshot
      if (JSON.stringify(editForm) === snapshot) {
        Object.assign(editForm, savedForm)
        editDialogVisible.value = false
      }
    }
    if (result.index_status === 'pending' || result.index_status === 'failed') ElMessage.warning(t('memoryPanel.docUpdated') + ' · ' + memoryIndexLabel(result.index_status))
    else ElMessage.success(t('memoryPanel.docUpdated'))
    await refreshMemoryState()
  } catch (error) { ElMessage.error(describeFailure(error, t('memoryPanel.docUpdateFailed'))) }
}

const removeDoc = async (id: string) => {
  if (removingDocIds.value.has(id) || deletePreflightLoading.value || batchActionLoading.value || deleteConfirmationOpen.value) return
  const doc = docs.value.find(item => item.id === id)
  if (!doc) return
  const context = memoryContextKey()
  const sessionId = docSessionId(doc)
  setDocRemoving(id, true)
  try {
    if (!await confirmMemoryDeletion([id], sessionId, t('memoryPanel.maintenanceDeleteConfirmTitle'), context)) return
    invalidateReads()
    let result: unknown
    try { result = await memoryClient.removeDoc(id, sessionId) }
    catch (error) {
      ElMessage.error(describeFailure(error, t('memoryPanel.docDeleteFailed')))
      await refreshAfterDeletion(false)
      return
    }
    reportMemoryDeletion(result, t('memoryPanel.docDeleted') + ' · ' + id)
    await refreshAfterDeletion()
  } finally { setDocRemoving(id, false) }
}

const deletePreviewMessage = (preview: MemoryDeletePreview) => {
  const parts = [t('memoryPanel.deletePreviewSummary', { total: preview.total_count, hard: preview.hard_delete_count })]
  if (preview.candidate_tombstone_count) parts.push(t('memoryPanel.deletePreviewCandidates', { count: preview.candidate_tombstone_count }))
  if (preview.affected_message_count) parts.push(t('memoryPanel.deletePreviewMessages', { count: preview.affected_message_count }))
  parts.push(memoryDeletionNote())
  const effects = preview.effects as MemoryDeletePreview['effects'] & { prefetch?: string }
  if (effects.prefetch === 'invalidated') parts.push(memoryText('预取缓存将失效。', 'Prefetch cache will be invalidated.'))
  return parts.join(t('memoryPanel.clauseSeparator'))
}

const forgetDoc = async (id: string) => {
  if (forgettingDocIds.value.has(id) || batchActionLoading.value || updateRequest.loading) return
  const doc = docs.value.find(item => item.id === id)
  if (!doc) return
  const context = memoryContextKey()
  const sessionId = docSessionId(doc)
  setPendingDocId(forgettingDocIds, id, true)
  try {
    await ElMessageBox.confirm(
      t('memoryPanel.forgetConfirmMessage'),
      t('memoryPanel.forgetConfirmTitle'),
      { confirmButtonText: t('memoryPanel.forgetConfirmAction'), cancelButtonText: t('memoryPanel.cancel'), type: 'warning' },
    )
  } catch {
    setPendingDocId(forgettingDocIds, id, false)
    return
  }

  if (context !== memoryContextKey() || memoryPanelDisposed) {
    setPendingDocId(forgettingDocIds, id, false)
    return
  }
  try {
    invalidateReads()
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    await softForgetDoc(id, { reason: 'user_soft_forget', session_id: sessionId })
    if (context === memoryContextKey() && selectedDocId.value === id) selectedDocId.value = fallbackId
    ElMessage.success(t('memoryPanel.forgetSuccess'))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.forgetFailed')))
  } finally {
    setPendingDocId(forgettingDocIds, id, false)
  }
}

const restoreForgottenDoc = async (id: string) => {
  if (restoringDocIds.value.has(id) || batchActionLoading.value || updateRequest.loading) return
  setPendingDocId(restoringDocIds, id, true)
  try {
    const doc = forgottenDocs.value.find(item => item.id === id) || docs.value.find(item => item.id === id)
    if (!doc) return
    const sessionId = docSessionId(doc)
    invalidateReads()
    await restoreDoc(id, { reason: 'user_restore', session_id: sessionId })
    ElMessage.success(t('memoryPanel.restoreSuccess'))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.restoreFailed')))
  } finally {
    setPendingDocId(restoringDocIds, id, false)
  }
}

const docScopeLabel = (doc: MemoryDoc) => scopeLabel(typeof doc.metadata?.scope === 'string' ? doc.metadata.scope : currentMemoryScope.value)

const docSourceValue = (doc: MemoryDoc) => {
  const source = stringMeta(doc, 'source')
  const confidenceSource = stringMeta(doc, 'confidence_source')
  const allowed = ['manual', 'session', 'relationship', 'reflection', 'import', 'profile', 'explicit', 'default']
  if (allowed.includes(source)) return source
  if (allowed.includes(confidenceSource)) return confidenceSource
  return 'manual'
}

const docSourceLabel = (doc: MemoryDoc) => {
  const label = docSourceValue(doc)
  const labels: Record<string, string> = {
    manual: t('memoryPanel.sourceShortManual'),
    session: t('memoryPanel.sourceShortSession'),
    relationship: t('memoryPanel.sourceRelationship'),
    reflection: t('memoryPanel.sourceReflection'),
    import: t('memoryPanel.sourceShortImport'),
    profile: t('memoryPanel.sourceProfile'),
    default: t('memoryPanel.sourceShortDefault'),
    explicit: t('memoryPanel.sourceShortExplicit'),
  }
  return labels[label] || label
}

const toDateTimeLocal = (value: unknown) => {
  if (typeof value !== 'string' || !value.trim()) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const toIsoOrNull = (value: string) => {
  if (!value.trim()) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toISOString() : null
}

const preserveTemporalPrecision = (draftValue: string, originalValue: unknown) =>
  draftValue === toDateTimeLocal(originalValue)
    ? (typeof originalValue === 'string' ? originalValue : null)
    : toIsoOrNull(draftValue)

const inspectorDraftFromDoc = (doc: MemoryDoc) => ({
  id: doc.id, text: doc.text || '', type: doc.type || 'fact', layer: doc.layer || 'semantic',
  importance: Number(doc.importance ?? 0.5), confidence: Number(doc.confidence ?? 0.72), source: docSourceValue(doc),
  validFrom: toDateTimeLocal(doc.valid_from ?? doc.metadata?.valid_from),
  validTo: toDateTimeLocal(doc.valid_to ?? doc.metadata?.valid_to),
  expiresAt: toDateTimeLocal(doc.expires_at ?? doc.metadata?.expires_at),
})
const inspectorDraftBase = ref('')
let inspectorDraftKey = ''
const inspectorDrafts = new Map<string, { draft: typeof inspectorDraft; base: string }>()
const hydrateInspectorDraft = (doc: MemoryDoc) => {
  Object.assign(inspectorDraft, inspectorDraftFromDoc(doc))
  inspectorDraftBase.value = JSON.stringify(inspectorDraft)
}
const resetInspectorDraft = () => {
  if (selectedDoc.value) {
    inspectorDrafts.delete(inspectorDraftKey)
    hydrateInspectorDraft(selectedDoc.value)
  }
}
const inspectorDraftDirty = computed(() => Boolean(inspectorDraft.id) && JSON.stringify(inspectorDraft) !== inspectorDraftBase.value)

const saveInspectorDraft = async () => {
  const doc = selectedDoc.value
  if (!doc || !inspectorDraft.text.trim() || inspectorDraftSaving.value) return
  const submitted = JSON.stringify(inspectorDraft)
  const key = inspectorDraftKey
  inspectorDraftSaving.value = true
  try {
    const result = await updateSelectedDoc(
      doc,
      {
        text: inspectorDraft.text.trim(),
        type: inspectorDraft.type || 'fact',
        layer: inspectorDraft.layer,
        importance: inspectorDraft.importance,
        confidence: inspectorDraft.confidence,
        confidence_source: inspectorDraft.source,
        metadata: {
          source: inspectorDraft.source,
          confidence_source: inspectorDraft.source,
          layer: inspectorDraft.layer,
          type: inspectorDraft.type || 'fact',
          valid_from: preserveTemporalPrecision(inspectorDraft.validFrom, doc.valid_from ?? doc.metadata?.valid_from),
          valid_to: preserveTemporalPrecision(inspectorDraft.validTo, doc.valid_to ?? doc.metadata?.valid_to),
          expires_at: preserveTemporalPrecision(inspectorDraft.expiresAt, doc.expires_at ?? doc.metadata?.expires_at),
        },
        edit_reason: 'inspector_edit',
      },
      t('memoryPanel.inspectorSaved'),
    )
    if (result?.status === 'updated' || result?.storage_status === 'saved') {
      const savedDraft = { ...JSON.parse(submitted), text: JSON.parse(submitted).text.trim() }
      const savedSnapshot = JSON.stringify(savedDraft)
      const cached = inspectorDrafts.get(key)
      if (cached && JSON.stringify(cached.draft) !== submitted) cached.base = savedSnapshot
      else inspectorDrafts.delete(key)
      if (key === inspectorDraftKey) {
        if (JSON.stringify(inspectorDraft) === submitted) Object.assign(inspectorDraft, savedDraft)
        inspectorDraftBase.value = savedSnapshot
      }
    }
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.inspectorSaveFailed')))
  } finally {
    inspectorDraftSaving.value = false
  }
}

const metadataPreview = (doc: MemoryDoc) => {
  try {
    return JSON.stringify(doc.metadata || {}, null, 2)
  } catch {
    return '{}'
  }
}

const docAuditEntries = (doc: MemoryDoc) => {
  const audit = doc.metadata?.audit
  return Array.isArray(audit) ? audit.filter(item => item && typeof item === 'object') as Array<Record<string, unknown>> : []
}

const auditActionLabel = (value: unknown) => {
  const map: Record<string, string> = {
    create: t('memoryPanel.auditCreate'),
    update: t('memoryPanel.auditUpdate'),
  }
  const key = String(value || 'event')
  return map[key] || key
}

const auditEntrySummary = (entry: Record<string, unknown>) => {
  const at = typeof entry.at === 'string' ? entry.at.replace('T', ' ').slice(0, 16) : ''
  const reason = typeof entry.reason === 'string' ? entry.reason : ''
  return [at, reason].filter(Boolean).join(' · ') || t('memoryPanel.noTimestamp')
}

watch(
  () => [docViewMode.value, docSortMode.value, filterLayer.value, searchText.value] as const,
  () => {
    visibleDocLimit.value = DOC_RENDER_BATCH_SIZE
  },
)

watch(
  () => [memoryContextKey(), selectedDoc.value] as const,
  () => {
    const doc = selectedDoc.value
    const nextKey = doc ? memoryContextKey() + ':' + doc.id : ''
    if (nextKey !== inspectorDraftKey) {
      if (inspectorDraftKey && inspectorDraftDirty.value) inspectorDrafts.set(inspectorDraftKey, { draft: { ...inspectorDraft }, base: inspectorDraftBase.value })
      inspectorDraftKey = nextKey
      const saved = inspectorDrafts.get(nextKey)
      if (saved) {
        Object.assign(inspectorDraft, saved.draft)
        inspectorDraftBase.value = saved.base
      } else if (doc) hydrateInspectorDraft(doc)
      else { inspectorDraft.id = ''; inspectorDraftBase.value = JSON.stringify(inspectorDraft) }
    } else if (doc && !inspectorDraftDirty.value && !inspectorDraftSaving.value) hydrateInspectorDraft(doc)
  },
  { immediate: true, flush: 'sync' },
)

watch(
  () => [route.name, route.params.workspaceId, route.params.sessionId, requestedMemoryDocId()] as const,
  () => {
    consumedEditRequest = ''
    openRequestedMemoryDoc()
  },
)

watch(
  () => [currentMemoryScope.value, activeWorkspace.value?.id, sessionStore.activeSession?.id] as const,
  ([scope]) => {
    memoryRefreshSequence += 1
    indexStatusSequence += 1
    consumedEditRequest = ''
    editDialogVisible.value = false
    invalidateReads(true)
    selectedDocId.value = ''
    feedbackById.value = {}
    feedbackErrors.value = {}
    deletePreflightError.value = ''
    importReport.value = null
    queryForm.scope = scope
    hydrateMaintenancePolicy()
    maintenancePreview.value = null
    maintenancePreviewPolicyKey.value = ''
    void refreshMemoryState()
  },
  { flush: 'sync' },
)

watch(() => queryForm.scope, () => {
  queryRequest.reset()
  queryResult.value = null
  feedbackById.value = {}
  feedbackErrors.value = {}
}, { flush: 'sync' })

const syncMemoryActivity = () => {
  const active = canReadMemory()
  if (active === memoryReadsActive) return
  memoryReadsActive = active
  if (active) {
    void refreshMemoryState()
  } else {
    memoryRefreshSequence += 1
    indexStatusSequence += 1
    stopRebuildMonitoring()
    memoryRefreshing.value = false
    invalidateReads()
  }
}

onActivated(() => {
  memoryPanelActive = true
  syncMemoryActivity()
})

onDeactivated(() => {
  memoryPanelActive = false
  advancedToolsVisible.value = false
  editDialogVisible.value = false
  syncMemoryActivity()
})

onBeforeUnmount(() => {
  memoryPanelDisposed = true
  syncMemoryActivity()
  stopRebuildMonitoring()
  document.removeEventListener('visibilitychange', syncMemoryActivity)
  invalidateReads(true)
})

onMounted(() => {
  memoryPanelActive = true
  queryForm.scope = currentMemoryScope.value
  document.addEventListener('visibilitychange', syncMemoryActivity)
  syncMemoryActivity()
})

</script>


<style scoped>
.memory-panel { display: flex; min-height: 0; flex-direction: column; gap: 16px; }
.memory-import-input { display: none; }
.memory-import-report { display: flex; flex-direction: column; gap: 9px; padding: 13px 15px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-raised); box-shadow: var(--yui-shadow-card); }
.import-report-head, .import-report-grid, .import-report-reasons { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.import-report-head { justify-content: space-between; }
.import-report-grid span, .import-report-reasons span, .import-report-note { color: var(--yui-muted); font-size: 11px; }
.import-report-grid strong { color: var(--yui-text); }
.import-report-reasons span { padding: 3px 7px; border-radius: var(--yui-radius-control); background: var(--yui-warning-soft); }
.import-report-note { margin: 0; }
.import-report-details summary { margin: 0; }
.import-report-details ul { display: flex; max-height: 220px; flex-direction: column; gap: 6px; margin: 8px 0 0; padding: 0; overflow: auto; list-style: none; }
.import-report-details li { display: grid; grid-template-columns: minmax(100px, 0.6fr) minmax(120px, 0.6fr) minmax(0, 1fr); gap: 8px; align-items: start; padding: 7px 9px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); }
.import-report-details li span, .import-report-details li small, .import-report-details > p { color: var(--yui-muted); font-size: 11px; overflow-wrap: anywhere; }
.scope-control { display: flex; align-items: center; gap: 7px; color: var(--yui-muted); font-size: 11px; }
.scope-control :deep(.el-select) { width: 108px; }
.scope-option { display: flex; min-width: 180px; flex-direction: column; gap: 2px; line-height: 1.25; }
.scope-option strong { color: var(--yui-text); font-size: 12px; font-weight: 600; }
.scope-option small { color: var(--yui-muted); font-size: 10px; }
.memory-tabs { display: flex; gap: 4px; padding: 4px 8px 0; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card) var(--yui-radius-card) 0 0; background: var(--yui-surface-raised); box-shadow: var(--yui-shadow-card); }
.memory-tabs button { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 8px 14px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--yui-muted); font: inherit; font-size: 13px; cursor: pointer; }
.memory-tabs button[aria-selected="true"] { border-bottom-color: var(--yui-accent); color: var(--yui-text); font-weight: 700; }
.memory-tabs button .tab-count { display: inline-grid; min-width: 18px; min-height: 18px; margin-left: 2px; place-items: center; border-radius: 9px; background: var(--yui-surface-muted); font-size: 10px; }
.memory-tabs button[aria-selected="true"] .tab-count { background: var(--yui-accent-soft); color: var(--yui-accent); }
.memory-tabs button:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: -2px; }
.tab-panel { min-width: 0; padding: 16px; border: 1px solid var(--yui-border); border-top: 0; border-radius: 0 0 var(--yui-radius-card) var(--yui-radius-card); background: var(--yui-surface-raised); box-shadow: var(--yui-shadow-card); }
.tab-panel > :deep(* + *) { margin-top: 18px; }
.dialog-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.dialog-grid :deep(.el-select), :deep(.el-dialog .el-select) { width: 100%; }
details summary { margin-bottom: 10px; color: var(--yui-muted); cursor: pointer; font-size: 12px; }
@media (max-width: 760px) { .scope-control span { display: none; }.memory-tabs { position: sticky; top: 0; z-index: 2; background: var(--yui-surface-raised); }.memory-tabs button { flex: 1; justify-content: center; padding-inline: 8px; }.tab-panel { padding: 12px; }.dialog-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .import-report-details li { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; } }
</style>

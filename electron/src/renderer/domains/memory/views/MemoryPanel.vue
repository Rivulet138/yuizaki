
<template>
  <PanelShell :title="t('memoryPanel.title')" tone="companion" density="compact">
    <template #status><span class="local-status" role="status">{{ t('memoryPanel.statusAutoOrganize') }}</span></template>
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
      <el-button data-testid="memory-refresh" circle plain :icon="Refresh" :title="t('memoryPanel.refresh')" :aria-label="t('memoryPanel.refresh')" :loading="docsRequest.loading" @click="refreshMemoryState" />
    </template>

    <div class="memory-panel">
      <section v-if="importReport" class="memory-import-report" aria-live="polite">
        <div class="import-report-head">
          <strong>{{ t('memoryPanel.lastImportTitle') }}</strong>
          <el-button link size="small" @click="importReport = null">{{ t('memoryPanel.close') }}</el-button>
        </div>
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
      <nav class="memory-tabs" role="tablist" :aria-label="t('memoryPanel.tabsAria')">
        <button v-for="(tab, index) in memoryTabs" :id="`memory-tab-${tab.value}`" :key="tab.value" type="button" role="tab" :tabindex="activeTab === tab.value ? 0 : -1" :aria-selected="activeTab === tab.value" :aria-controls="`memory-panel-${tab.value}`" @click="activeTab = tab.value" @keydown="onMemoryTabKeydown($event, index)">
          <el-icon aria-hidden="true"><component :is="tab.icon" /></el-icon><span class="tab-label">{{ tab.label }}</span><span v-if="tab.count !== undefined" class="tab-count">{{ tab.count }}</span>
        </button>
      </nav>
      <div v-show="activeTab === 'library'" id="memory-panel-library" role="tabpanel" aria-labelledby="memory-tab-library" class="tab-panel">
        <MemoryLibrary
          :visible-docs="visibleDocs" :filtered-count="filteredDocs.length" :remaining-count="remainingFilteredDocCount" :selected-doc="selectedDoc"
          :view-mode="docViewMode" :sort-mode="docSortMode" :filter-layer="filterLayer" :search-text="searchText" :view-options="docViewOptions"
          :layers="layers" :source-options="memorySourceOptions" :loading="docsRequest.loading" :error="docsRequest.error"
          :has-filters="hasDocFilters" :batch-delete-label="batchDeleteLabel"
          :batch-action-loading="batchActionLoading" :batch-action-disabled="batchActionDisabled" :inspector-draft="inspectorDraft"
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
      <MemoryAdvancedTools
        :index-status="indexStatus" :rebuild-job="indexStatus?.job ?? null" :index-status-label="indexStatusLabel" :index-availability-label="indexAvailabilityLabel" :index-status-tone="indexStatusTone"
        :doc-count="docs.length" :rebuild-index-loading="rebuildIndexLoading" :query-form="queryForm" :layers="layers"
        :effective-query-layers="effectiveQueryLayers" :query-loading="queryRequest.loading"
        :query-error="queryRequest.error" :query-result="queryResult" :query-summary="querySummary"
        :filter-reason-text="filterReasonText"
        :maintenance-policy="maintenancePolicy" :maintenance-preview="maintenancePreview"
        :maintenance-preview-matches-policy="maintenancePreviewMatchesPolicy" :maintenance-saving="maintenanceSaving"
        :maintenance-preview-loading="maintenancePreviewLoading" :maintenance-apply-loading="maintenanceApplyLoading"
        :format-latency="formatLatency" :compact-text="compactText" :maintenance-reason-label="maintenanceReasonLabel"
         @rebuild-index="rebuildMemoryIndex" @cancel-rebuild-index="cancelMemoryIndexRebuild" @query="submitQuery" @toggle-query-layer="toggleQueryLayer"
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
      <template #footer><el-button @click="editDialogVisible = false">{{ t('memoryPanel.cancel') }}</el-button><el-button type="primary" :loading="updateRequest.loading" :disabled="!editForm.text.trim()" @click="submitEditDoc">{{ t('memoryPanel.saveChanges') }}</el-button></template>
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
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { ElDialog, ElDrawer, ElForm, ElFormItem, ElInput, ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/drawer/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input/style/css'
import { Collection, DataAnalysis, Refresh, Tools, User } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import MemoryAdvancedTools from '../components/MemoryAdvancedTools.vue'
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
import { memoryInspectorActionsKey } from '../components/memory-panel-types'
import { describeFailure } from '@/shared/errors/describe-error'
import { t } from '@/i18n'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type DocViewMode = 'all' | 'recallable' | 'review' | 'important' | 'hits'
type DocSortMode = 'updated' | 'importance' | 'quality' | 'confidence'
type MemoryScope = 'global' | 'workspace' | 'session'
type MemoryTab = 'library' | 'review' | 'overview'

const {
  docs, operations, forgottenDocs, reviewCandidates, overview, queryResult,
  docsRequest, forgottenDocsRequest, overviewRequest, candidatesRequest, updateRequest, queryRequest, operationsRequest,
  loadDocs, loadForgottenDocs, loadCandidates, loadOperations, loadOverview, updateDoc, softForgetDoc, restoreDoc, reviewCandidate, queryMemory, recordRecallFeedback,
} = useMemoryDomain()
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
const inspectorDraft = reactive({
  id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual',
  validFrom: '', validTo: '', expiresAt: '',
})
const rebuildIndexLoading = ref(false)
let activeRebuildJobId = ''
let memoryPanelDisposed = false
const batchActionLoading = ref(false)
const workspaceScopeSaving = ref(false)
const exportLoading = ref(false)
const importLoading = ref(false)
const importReport = ref<MemoryImportResult | null>(null)
const deletePreview = ref<MemoryDeletePreview | null>(null)
const memoryImportInput = ref<HTMLInputElement | null>(null)
const inspectorDraftSaving = ref(false)
const forgettingDocIds = ref(new Set<string>())
const restoringDocIds = ref(new Set<string>())
const removingDocIds = ref(new Set<string>())
const batchDeleteProgress = reactive({ active: false, total: 0, done: 0 })
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
    maintenancePreview.value = await memoryClient.previewMaintenance(maintenancePayload())
    maintenancePreviewPolicyKey.value = maintenancePolicyKey()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.maintenancePreviewFailed')))
  } finally {
    maintenancePreviewLoading.value = false
  }
}

const applyMemoryMaintenance = async () => {
  if (maintenanceApplyLoading.value) return
  if (!maintenancePreviewMatchesPolicy.value) {
    ElMessage.warning(t('memoryPanel.maintenancePolicyChanged'))
    return
  }
  const previewToken = maintenancePreview.value?.preview_token
  if (!previewToken) {
    ElMessage.warning(t('memoryPanel.maintenancePreviewStale'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('memoryPanel.maintenanceDeleteConfirmMessage', { count: maintenancePreview.value?.summary.delete_count ?? 0 }),
      t('memoryPanel.maintenanceDeleteConfirmTitle'),
      { confirmButtonText: t('memoryPanel.permanentDelete'), cancelButtonText: t('memoryPanel.cancel'), type: 'warning' },
    )
  } catch {
    return
  }
  maintenanceApplyLoading.value = true
  try {
    const result = await memoryClient.applyMaintenance({
      ...maintenancePayload(),
      preview_token: previewToken,
      confirmation: 'PERMANENT_DELETE',
    })
    ElMessage.success(t('memoryPanel.maintenanceDeleted', { count: result.changed_count }))
    await refreshMemoryState()
    try {
      maintenancePreview.value = await memoryClient.previewMaintenance(maintenancePayload())
      maintenancePreviewPolicyKey.value = maintenancePolicyKey()
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
  if (mode === 'recallable') return true
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
    selectedDoc.value?.id,
    currentMemoryScope.value,
    activeWorkspace.value.id,
    sessionStore.activeSession?.id,
  ] as const,
  ([id, scope, workspaceId, sessionId]) => {
    if (!id) {
    operationsRequest.reset()
    return
    }
    void loadOperations(id, {
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
const batchActionDisabled = computed(() => batchActionLoading.value || !hasDocFilters.value || batchTargetCount.value === 0)
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

const scopedDocOptions = () => ({
  scope: currentMemoryScope.value,
  workspaceId: activeWorkspace.value?.id,
  sessionId: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
})

const loadScopedDocs = () => loadDocs(scopedDocOptions())

const refreshIndexStatus = async () => {
  try {
    indexStatus.value = await memoryClient.getIndexStatus()
    const job = indexStatus.value.job
    if (job && ['queued', 'running', 'cancelling'].includes(job.state) && activeRebuildJobId !== job.job_id) {
      rebuildIndexLoading.value = true
      void monitorMemoryIndexRebuild(job.job_id, false)
    }
  } catch (error) {
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

const refreshMemoryState = async () => {
  const options = scopedDocOptions()
  await Promise.all([
    loadDocs(options),
    loadOverview(options),
    loadForgottenDocs(options),
    loadCandidates(options),
  ])
  try {
    await refreshIndexStatus()
  } catch (error) {
    console.debug('[MemoryPanel] failed to refresh index status:', error)
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
  try {
    const payload = await memoryClient.exportDocs({ ...scopedDocOptions(), includeState: 'all' })
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `yuizaki-memory-${currentMemoryScope.value}-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success(t('memoryPanel.exportSuccess', { count: payload.count }))
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.exportFailed')))
  } finally {
    exportLoading.value = false
  }
}

const handleMemoryImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
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
    if (!importDocs.length) throw new Error(t('memoryPanel.importEmpty'))
    const existingIds = new Set(docs.value.map(doc => doc.id))
    const duplicateCount = importDocs.filter(doc => doc.id && existingIds.has(doc.id)).length
    await ElMessageBox.confirm(
      t('memoryPanel.importConfirmMessage', {
        count: importDocs.length,
        scope: scopeLabel(currentMemoryScope.value),
        note: duplicateCount ? t('memoryPanel.importConfirmNote', { count: duplicateCount }) : '',
      }),
      t('memoryPanel.importConfirmTitle'),
      { confirmButtonText: t('memoryPanel.importStart'), cancelButtonText: t('memoryPanel.cancel'), type: 'info' },
    )
    const result = await memoryClient.importDocs({
      format: 'yuizaki-memory-export',
      version: 1,
      docs: importDocs.map(doc => ({ id: doc.id, text: doc.text, metadata: doc.metadata })),
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'workspace' ? activeWorkspace.value?.id : undefined,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      conflict: 'skip',
    })
    importReport.value = result
    ElMessage.success(t('memoryPanel.importSuccess', { imported: result.imported_count, skipped: result.skipped_count }))
    await refreshMemoryState()
  } catch (error) {
    if (error !== 'cancel' && !(error instanceof Error && error.message === 'cancel')) {
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
const waitForRebuildPoll = () => new Promise(resolve => window.setTimeout(resolve, 500))

const projectRebuildJob = (job: MemoryIndexRebuildJob, indexState: string) => {
  const current = indexStatus.value
  indexStatus.value = {
    status: indexState,
    count: current?.count ?? docs.value.length,
    backend: current?.backend,
    healthy: current?.healthy ?? true,
    message: current?.message,
    metadata: current?.metadata,
    job,
  }
}

const monitorMemoryIndexRebuild = async (jobId: string, announceCompletion: boolean) => {
  activeRebuildJobId = jobId
  try {
    while (!memoryPanelDisposed && activeRebuildJobId === jobId) {
      const response = await memoryClient.getIndexRebuildJob(jobId)
      projectRebuildJob(response.job, response.index_status)
      if (rebuildTerminalStates.has(response.job.state)) {
        if (response.job.state === 'completed') {
          const indexedCount = Number(response.job.result?.indexed_count ?? response.job.processed_count)
          if (announceCompletion) ElMessage.success(t('memoryPanel.indexRebuilt', { count: indexedCount }))
          await refreshMemoryState()
        } else if (response.job.state === 'cancelled') {
          if (announceCompletion) ElMessage.info(t('memoryPanel.indexRebuildCancelled'))
          await refreshIndexStatus()
        } else if (announceCompletion) {
          ElMessage.error(response.job.last_error || t('memoryPanel.indexRebuildFailedRetry'))
        }
        break
      }
      await waitForRebuildPoll()
    }
  } catch (error) {
    if (!memoryPanelDisposed) {
      // A backend restart can discard the in-memory job; refresh once so stale
      // progress is not left looking active and the authority status is visible.
      if (error instanceof Error && /404|not found/i.test(error.message)) {
        await refreshIndexStatus().catch(() => undefined)
      } else {
        ElMessage.error(describeFailure(error, t('memoryPanel.indexRebuildProgressFailed')))
      }
    }
  } finally {
    if (activeRebuildJobId === jobId) {
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
    projectRebuildJob(response.job, response.index_status)
    await monitorMemoryIndexRebuild(response.job.job_id, true)
  } catch (error) {
    rebuildIndexLoading.value = false
    ElMessage.error(describeFailure(error, t('memoryPanel.indexRebuildFailed')))
  }
}

const cancelMemoryIndexRebuild = async () => {
  const job = indexStatus.value?.job
  if (!job || !['queued', 'running', 'cancelling'].includes(job.state)) return
  try {
    const response = await memoryClient.cancelIndexRebuild(job.job_id)
    projectRebuildJob(response.job, response.index_status)
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
  if (!queryForm.query.trim()) return
  await queryMemory({
    query: queryForm.query.trim(),
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
  try {
    const doc = queryResult.value?.results.find(item => item.id === payload.id)
    await recordRecallFeedback(payload.id, payload.feedback, doc ? docSessionId(doc) : scopedDocOptions().sessionId)
    ElMessage.success(payload.feedback === 'helpful' ? t('memoryPanel.feedbackHelpful') : t('memoryPanel.feedbackRecorded'))
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.feedbackFailed')))
  }
}

const openEditDoc = (doc: MemoryDoc) => {
  editForm.id = doc.id
  editForm.text = doc.text || ''
  editForm.type = doc.type || 'fact'
  editForm.layer = doc.layer || 'semantic'
  editForm.importance = Number(doc.importance ?? 0.5)
  editForm.confidence = Number(doc.confidence ?? 0.72)
  editForm.source = docSourceValue(doc)
  editForm.metadataJson = JSON.stringify(doc.metadata || {}, null, 2)
  editDialogVisible.value = true
}

const openRequestedMemoryDoc = () => {
  const query = window.location.hash.split('?')[1] || ''
  const requestedId = new URLSearchParams(query).get('edit')?.trim() || ''
  if (!requestedId) return
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
  const result = await updateDoc(doc.id, buildDocUpdatePayload(doc, overrides))
  if (result?.status === 'updated') {
    ElMessage.success(successMessage)
    selectedDocId.value = doc.id
    await refreshMemoryState()
  }
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
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info(t('memoryPanel.batchNeedsFilters'))
    return
  }
  if (!targets.length) return
  try {
    await ElMessageBox.confirm(
      t('memoryPanel.batchConfirmMessage', { count: targets.length, action: actionLabel }),
      t('memoryPanel.batchConfirmTitle'),
      {
        confirmButtonText: actionLabel,
        cancelButtonText: t('memoryPanel.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchActionLoading.value = true
  try {
    for (const doc of targets) {
      await updateDoc(doc.id, buildDocUpdatePayload(doc, buildOverrides(doc)))
    }
    ElMessage.success(t('memoryPanel.batchProcessed', { count: targets.length }))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.batchFailed')))
  } finally {
    batchActionLoading.value = false
  }
}

const batchBoostVisibleDocs = () => batchUpdateVisibleDocs(t('memoryPanel.batchBoostAction'), doc => ({
  importance: Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85)),
  edit_reason: 'batch_boost_importance',
}))

const batchDeleteVisibleDocs = async () => {
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info(t('memoryPanel.batchDeleteSelectionRequired'))
    return
  }
  if (!targets.length) return
  const targetIds = new Set(targets.map(doc => doc.id))
  const ids = [...targetIds]
  const previousDocs = docs.value.slice()
  const previousSelectedDocId = selectedDocId.value
  const nextSelectedId = docs.value.find(doc => !targetIds.has(doc.id))?.id || ''
  try {
    deletePreview.value = await memoryClient.previewDelete(ids, scopedDocOptions().sessionId)
    await ElMessageBox.confirm(
      deletePreviewMessage(deletePreview.value),
      t('memoryPanel.batchDeleteConfirmTitle', { count: targets.length }),
      {
        confirmButtonText: t('memoryPanel.permanentDelete'),
        cancelButtonText: t('memoryPanel.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchActionLoading.value = true
  batchDeleteProgress.active = true
  batchDeleteProgress.total = ids.length
  batchDeleteProgress.done = 0
  try {
    docs.value = docs.value.filter(doc => !targetIds.has(doc.id))
    if (targetIds.has(selectedDocId.value)) selectedDocId.value = nextSelectedId
    const result = await memoryClient.removeDocs(ids, scopedDocOptions().sessionId)
    batchDeleteProgress.done = result.deleted_count ?? ids.length
    ElMessage.success(t('memoryPanel.batchDeleted', { count: batchDeleteProgress.done }))
    await refreshIndexStatus().catch(error => console.debug('[MemoryPanel] failed to refresh index status after batch delete:', error))
  } catch (error) {
    docs.value = previousDocs
    selectedDocId.value = previousSelectedDocId
    ElMessage.error(describeFailure(error, t('memoryPanel.batchDeleteFailed')))
  } finally {
    batchDeleteProgress.active = false
    batchActionLoading.value = false
  }
}

const submitEditDoc = async () => {
  if (!editForm.id || !editForm.text.trim()) return
  try {
    const targetDoc = docs.value.find(doc => doc.id === editForm.id)
    const metadata = {
      ...parseJsonObject(editForm.metadataJson, 'Metadata'),
      source: editForm.source,
      confidence_source: editForm.source,
    }
    const payload = targetDoc ? buildDocUpdatePayload(targetDoc, {
      text: editForm.text.trim(),
      type: editForm.type || 'fact',
      layer: editForm.layer,
      importance: editForm.importance,
      confidence: editForm.confidence,
      confidence_source: editForm.source,
      metadata,
      edit_reason: 'manual_edit',
    }) : {
      text: editForm.text.trim(),
      type: editForm.type || 'fact',
      layer: editForm.layer,
      importance: editForm.importance,
      confidence: editForm.confidence,
      confidence_source: editForm.source,
      metadata,
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      edit_reason: 'manual_edit',
    }
    const result = await updateDoc(editForm.id, payload)
    if (result?.status === 'updated') {
      ElMessage.success(t('memoryPanel.docUpdated'))
      editDialogVisible.value = false
      selectedDocId.value = editForm.id
      void refreshMemoryState()
    }
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.docUpdateFailed')))
  }
}

const removeDoc = async (id: string) => {
  if (removingDocIds.value.has(id)) return
  const doc = docs.value.find(item => item.id === id)
  try {
    deletePreview.value = await memoryClient.previewDelete([id], doc ? docSessionId(doc) : scopedDocOptions().sessionId)
    await ElMessageBox.confirm(
      deletePreviewMessage(deletePreview.value),
      t('memoryPanel.maintenanceDeleteConfirmTitle'),
      {
        confirmButtonText: t('memoryPanel.permanentDelete'),
        cancelButtonText: t('memoryPanel.cancel'),

        type: 'warning',
      },
    )
  } catch {
    return
  }

  setDocRemoving(id, true)
  try {
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    await memoryClient.removeDoc(id, doc ? docSessionId(doc) : scopedDocOptions().sessionId)
    ElMessage.success(t('memoryPanel.docDeleted'))
    if (selectedDocId.value === id) selectedDocId.value = fallbackId
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.docDeleteFailed')))
  } finally {
    setDocRemoving(id, false)
  }
}

const deletePreviewMessage = (preview: MemoryDeletePreview) => {
  const parts = [t('memoryPanel.deletePreviewSummary', { total: preview.total_count, hard: preview.hard_delete_count })]
  if (preview.candidate_tombstone_count) parts.push(t('memoryPanel.deletePreviewCandidates', { count: preview.candidate_tombstone_count }))
  if (preview.affected_message_count) parts.push(t('memoryPanel.deletePreviewMessages', { count: preview.affected_message_count }))
  parts.push(t('memoryPanel.deletePreviewIndexNote'))
  return parts.join(t('memoryPanel.clauseSeparator'))
}

const forgetDoc = async (id: string) => {
  if (forgettingDocIds.value.has(id)) return
  try {
    await ElMessageBox.confirm(
      t('memoryPanel.forgetConfirmMessage'),
      t('memoryPanel.forgetConfirmTitle'),
      { confirmButtonText: t('memoryPanel.forgetConfirmAction'), cancelButtonText: t('memoryPanel.cancel'), type: 'warning' },
    )
  } catch {
    return
  }

  setPendingDocId(forgettingDocIds, id, true)
  try {
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    const doc = docs.value.find(item => item.id === id)
    await softForgetDoc(id, { reason: 'user_soft_forget', session_id: doc ? docSessionId(doc) : scopedDocOptions().sessionId })
    if (selectedDocId.value === id) selectedDocId.value = fallbackId
    ElMessage.success(t('memoryPanel.forgetSuccess'))
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(describeFailure(error, t('memoryPanel.forgetFailed')))
  } finally {
    setPendingDocId(forgettingDocIds, id, false)
  }
}

const restoreForgottenDoc = async (id: string) => {
  if (restoringDocIds.value.has(id)) return
  setPendingDocId(restoringDocIds, id, true)
  try {
    const doc = forgottenDocs.value.find(item => item.id === id) || docs.value.find(item => item.id === id)
    await restoreDoc(id, { reason: 'user_restore', session_id: doc ? docSessionId(doc) : scopedDocOptions().sessionId })
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

const hydrateInspectorDraft = (doc: MemoryDoc) => {
  inspectorDraft.id = doc.id
  inspectorDraft.text = doc.text || ''
  inspectorDraft.type = doc.type || 'fact'
  inspectorDraft.layer = doc.layer || 'semantic'
  inspectorDraft.importance = Number(doc.importance ?? 0.5)
  inspectorDraft.confidence = Number(doc.confidence ?? 0.72)
  inspectorDraft.source = docSourceValue(doc)
  inspectorDraft.validFrom = toDateTimeLocal(doc.valid_from ?? doc.metadata?.valid_from)
  inspectorDraft.validTo = toDateTimeLocal(doc.valid_to ?? doc.metadata?.valid_to)
  inspectorDraft.expiresAt = toDateTimeLocal(doc.expires_at ?? doc.metadata?.expires_at)
}

const resetInspectorDraft = () => {
  if (selectedDoc.value) hydrateInspectorDraft(selectedDoc.value)
}

const inspectorDraftDirty = computed(() => {
  const doc = selectedDoc.value
  if (!doc || inspectorDraft.id !== doc.id) return false
  return inspectorDraft.text !== (doc.text || '')
    || inspectorDraft.type !== (doc.type || 'fact')
    || inspectorDraft.layer !== (doc.layer || 'semantic')
    || Number(inspectorDraft.importance.toFixed(4)) !== Number(Number(doc.importance ?? 0.5).toFixed(4))
    || Number(inspectorDraft.confidence.toFixed(4)) !== Number(Number(doc.confidence ?? 0.72).toFixed(4))
    || inspectorDraft.source !== docSourceValue(doc)
    || inspectorDraft.validFrom !== toDateTimeLocal(doc.valid_from ?? doc.metadata?.valid_from)
    || inspectorDraft.validTo !== toDateTimeLocal(doc.valid_to ?? doc.metadata?.valid_to)
    || inspectorDraft.expiresAt !== toDateTimeLocal(doc.expires_at ?? doc.metadata?.expires_at)
})

const saveInspectorDraft = async () => {
  const doc = selectedDoc.value
  if (!doc || !inspectorDraft.text.trim() || inspectorDraftSaving.value) return
  inspectorDraftSaving.value = true
  try {
    await updateSelectedDoc(
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
  () => selectedDoc.value ? [
    selectedDoc.value.id,
    selectedDoc.value.text,
    selectedDoc.value.type,
    selectedDoc.value.layer,
    selectedDoc.value.importance,
    selectedDoc.value.confidence,
    docSourceValue(selectedDoc.value),
    selectedDoc.value.valid_from ?? selectedDoc.value.metadata?.valid_from,
    selectedDoc.value.valid_to ?? selectedDoc.value.metadata?.valid_to,
    selectedDoc.value.expires_at ?? selectedDoc.value.metadata?.expires_at,
  ] : [],
  () => {
    if (selectedDoc.value && !inspectorDraftSaving.value) hydrateInspectorDraft(selectedDoc.value)
  },
  { immediate: true },
)

watch(
  () => [currentMemoryScope.value, activeWorkspace.value?.id, sessionStore.activeSession?.id] as const,
  ([scope]) => {
    queryForm.scope = scope
    hydrateMaintenancePolicy()
    maintenancePreview.value = null
    maintenancePreviewPolicyKey.value = ''
    void refreshMemoryState()
  },
)

onBeforeUnmount(() => {
  memoryPanelDisposed = true
  activeRebuildJobId = ''
})

onMounted(async () => {
  memoryPanelDisposed = false
  queryForm.scope = currentMemoryScope.value
  await refreshMemoryState()
  openRequestedMemoryDoc()
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
.local-status { color: var(--yui-muted); font-size: 11px; }
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

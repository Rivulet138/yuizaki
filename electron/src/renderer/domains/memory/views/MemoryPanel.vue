
<template>
  <PanelShell title="记忆管理" subtitle="查看、编辑和控制记忆召回" tone="companion" density="compact">
    <template #status><span class="local-status" role="status">本机保存 · {{ scopeLabel(currentMemoryScope) }}</span></template>
    <template #actions>
      <label class="scope-control"><span>当前范围</span><el-select :model-value="currentMemoryScope" size="small" :disabled="workspaceScopeSaving" aria-label="当前记忆范围" @change="updateDefaultMemoryScope"><el-option v-for="scope in memoryScopeOptions" :key="scope.value" :label="scope.label" :value="scope.value" /></el-select></label>
      <el-button data-testid="memory-advanced-tools-toggle" circle plain :icon="Tools" :type="advancedToolsVisible ? 'primary' : 'default'" title="高级工具" aria-label="打开高级工具" :aria-expanded="advancedToolsVisible" @click="advancedToolsVisible = true" />
      <el-button data-testid="memory-refresh" circle plain :icon="Refresh" title="刷新记忆" aria-label="刷新记忆" :loading="docsRequest.loading" @click="refreshMemoryState" />
    </template>

    <div class="memory-panel">
      <section class="memory-welcome" aria-labelledby="memory-welcome-title">
        <div class="welcome-copy">
          <span class="welcome-kicker"><el-icon><User /></el-icon> 当前范围</span>
          <h3 id="memory-welcome-title">记忆状态</h3>
          <p>数据保存在本机。可查看来源、修改内容、停止召回或恢复。</p>
        </div>
        <div class="memory-health" aria-label="当前记忆状态">
          <div class="scope-pill"><span>当前范围</span><strong>{{ scopeLabel(currentMemoryScope) }}</strong></div>
          <div class="health-stat"><strong>{{ overview?.recallable ?? docs.length }}</strong><span>可召回</span></div>
          <div class="health-stat" :class="{ attention: reviewDocs.length > 0 }"><strong>{{ reviewDocs.length }}</strong><span>待确认</span></div>
        </div>
      </section>
      <nav class="memory-tabs" role="tablist" aria-label="记忆视图">
        <button v-for="(tab, index) in memoryTabs" :id="`memory-tab-${tab.value}`" :key="tab.value" type="button" role="tab" :tabindex="activeTab === tab.value ? 0 : -1" :aria-selected="activeTab === tab.value" :aria-controls="`memory-panel-${tab.value}`" @click="activeTab = tab.value" @keydown="onMemoryTabKeydown($event, index)">
          <el-icon aria-hidden="true"><component :is="tab.icon" /></el-icon><span class="tab-label">{{ tab.label }}</span><span v-if="tab.count !== undefined" class="tab-count">{{ tab.count }}</span>
        </button>
      </nav>
      <div class="tab-context" role="status"><strong>{{ activeTabMeta.label }}</strong><span>{{ activeTabMeta.description }}</span></div>

      <div v-show="activeTab === 'library'" id="memory-panel-library" role="tabpanel" aria-labelledby="memory-tab-library" class="tab-panel">
        <MemoryQuickCapture :form="form" :layers="layers" :type-options="memoryTypePresets" :source-options="memorySourceOptions" :selected-layer-description="selectedLayerDefinition.desc" :duplicate-candidates="duplicateCandidates" :loading="addRequest.loading" @update-form="Object.assign(form, $event)" @submit="submitMemory" />
        <MemoryLibrary
          :visible-docs="visibleDocs" :filtered-count="filteredDocs.length" :remaining-count="remainingFilteredDocCount" :selected-doc="selectedDoc"
          :view-mode="docViewMode" :sort-mode="docSortMode" :filter-layer="filterLayer" :search-text="searchText" :view-options="docViewOptions"
          :layers="layers" :source-options="memorySourceOptions" :loading="docsRequest.loading" :error="docsRequest.error"
          :has-filters="hasDocFilters" :batch-action-hint="batchActionHint" :batch-delete-label="batchDeleteLabel"
          :batch-action-loading="batchActionLoading" :batch-action-disabled="batchActionDisabled" :inspector-draft="inspectorDraft"
          :inspector-draft-dirty="inspectorDraftDirty" :inspector-draft-saving="inspectorDraftSaving" :forgetting-doc-ids="forgettingDocIds" :removing-doc-ids="removingDocIds"
          :doc-view-count="docViewCount" :is-query-hit="isQueryHit" :layer-tag-type="layerTagType" :format-score="formatScore"
          :doc-updated-label="docUpdatedLabel" :doc-scope-label="docScopeLabel" :doc-source-label="docSourceLabel" :quality-percent="qualityPercent"
          :metadata-preview="metadataPreview" :doc-audit-entries="docAuditEntries" :audit-action-label="auditActionLabel" :audit-entry-summary="auditEntrySummary"
          @update:view-mode="docViewMode = $event" @update:sort-mode="docSortMode = $event" @update:filter-layer="filterLayer = $event" @update:search-text="searchText = $event"
          @select="selectDoc" @edit="openEditDoc" @boost="boostDocImportance" @forget="forgetDoc" @remove="removeDoc" @move-layer="moveDocLayer"
          @retry="loadScopedDocs" @show-more="showMoreDocs" @reset-filters="resetDocFilters" @batch-boost="batchBoostVisibleDocs"
          @batch-delete="batchDeleteVisibleDocs" @save-inspector="saveInspectorDraft" @reset-inspector="resetInspectorDraft"
          @update-inspector-draft="Object.assign(inspectorDraft, $event)"
        />
      </div>
      <div v-show="activeTab === 'review'" id="memory-panel-review" role="tabpanel" aria-labelledby="memory-tab-review" class="tab-panel"><MemoryReviewQueue :docs="reviewDocs" :compact-text="compactText" :quality-percent="qualityPercent" @review="openEditDoc" /></div>
      <div v-show="activeTab === 'overview'" id="memory-panel-overview" role="tabpanel" aria-labelledby="memory-tab-overview" class="tab-panel">
        <MemoryOverview
          :overview="overview" :forgotten-docs="forgottenDocs" :layers="layerStats" :selected-layer="filterLayer"
          :loading="overviewRequest.loading || forgottenDocsRequest.loading" :error="overviewRequest.error || forgottenDocsRequest.error"
          :restoring-doc-ids="restoringDocIds" @select-layer="openLayerInLibrary" @restore="restoreForgottenDoc"
        />
      </div>
    </div>

    <el-drawer v-model="advancedToolsVisible" title="高级记忆工具" size="min(560px, 92vw)" append-to-body>
      <MemoryAdvancedTools
        :index-status="indexStatus" :index-status-label="indexStatusLabel" :index-availability-label="indexAvailabilityLabel" :index-status-tone="indexStatusTone"
        :doc-count="docs.length" :rebuild-index-loading="rebuildIndexLoading" :query-form="queryForm" :layers="layers"
        :effective-query-layers="effectiveQueryLayers" :query-loading="queryRequest.loading" :raw-query-loading="rawQueryRequest.loading"
        :query-error="queryRequest.error" :query-result="queryResult" :query-trace="queryTrace" :query-summary="querySummary"
        :filter-reason-text="filterReasonText" :selected-trace-ids="selectedTraceIds" :hidden-trace-id-count="hiddenTraceIdCount"
        :document-form="docForm" :document-loading="docWriteLoading" :maintenance-policy="maintenancePolicy" :maintenance-preview="maintenancePreview"
        :maintenance-preview-matches-policy="maintenancePreviewMatchesPolicy" :maintenance-saving="maintenanceSaving"
        :maintenance-preview-loading="maintenancePreviewLoading" :maintenance-apply-loading="maintenanceApplyLoading"
        :format-latency="formatLatency" :compact-text="compactText" :maintenance-reason-label="maintenanceReasonLabel"
        @rebuild-index="rebuildMemoryIndex" @query="submitQuery" @raw-query="submitRawQuery" @toggle-query-layer="toggleQueryLayer"
        @reset-query-layers="resetQueryLayers" @select-result="selectDocFromAdvanced" @write-document="submitDocument"
        @save-maintenance="saveMemoryPolicy" @preview-maintenance="previewMemoryMaintenance" @apply-maintenance="applyMemoryMaintenance"
        @update-query="Object.assign(queryForm, $event)" @update-document="Object.assign(docForm, $event)" @update-maintenance="Object.assign(maintenancePolicy, $event)"
      />
    </el-drawer>

    <el-dialog v-model="editDialogVisible" title="编辑记忆" width="min(640px, 92vw)">
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="记忆内容"><el-input v-model="editForm.text" type="textarea" :rows="5" /></el-form-item>
        <div class="dialog-grid"><el-form-item label="记忆层级"><el-select v-model="editForm.layer"><el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" /></el-select></el-form-item><el-form-item label="数据类型"><el-input v-model="editForm.type" /></el-form-item></div>
        <div class="dialog-grid"><el-form-item :label="`重要度：${editForm.importance.toFixed(2)}`"><el-slider v-model="editForm.importance" :min="0" :max="1" :step="0.05" /></el-form-item><el-form-item :label="`置信度：${editForm.confidence.toFixed(2)}`"><el-slider v-model="editForm.confidence" :min="0" :max="1" :step="0.05" /></el-form-item></div>
        <el-form-item label="来源"><el-select v-model="editForm.source"><el-option v-for="source in memorySourceOptions" :key="source.value" :label="source.label" :value="source.value" /></el-select></el-form-item>
        <details><summary>元数据 JSON</summary><el-input v-model="editForm.metadataJson" type="textarea" :rows="4" /></details>
      </el-form>
      <template #footer><el-button @click="editDialogVisible = false">取消</el-button><el-button type="primary" :loading="updateRequest.loading" :disabled="!editForm.text.trim()" @click="submitEditDoc">保存修改</el-button></template>
    </el-dialog>
  </PanelShell>
</template>


<script setup lang="ts">
import { computed, nextTick, onMounted, provide, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, DataAnalysis, Refresh, Tools, User } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import MemoryAdvancedTools from '../components/MemoryAdvancedTools.vue'
import MemoryLibrary from '../components/MemoryLibrary.vue'
import MemoryOverview from '../components/MemoryOverview.vue'
import MemoryQuickCapture from '../components/MemoryQuickCapture.vue'
import MemoryReviewQueue from '../components/MemoryReviewQueue.vue'
import { normalizeDuplicateCandidates, useMemoryDomain } from '../composables/useMemoryDomain'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { systemClient } from '@/api/client'
import { memoryClient } from '@/api/clients/memory-client'
import type { MemoryIndexStatus, MemoryMaintenancePolicyPayload, MemoryMaintenancePreview } from '@/api/clients/memory-client'
import { getMemoryIndexUiStatus } from '../memory-index-status'
import type { MemoryDoc, MemoryDuplicateCandidate } from '../composables/useMemoryDomain'
import { memoryInspectorActionsKey } from '../components/memory-panel-types'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type DocViewMode = 'all' | 'recallable' | 'review' | 'important' | 'hits'
type DocSortMode = 'updated' | 'importance' | 'quality' | 'confidence'
type MemoryScope = 'global' | 'workspace' | 'session'
type MemoryTab = 'library' | 'review' | 'overview'

const {
  docs, forgottenDocs, overview, queryResult,
  docsRequest, forgottenDocsRequest, overviewRequest, addRequest, updateRequest, queryRequest, rawQueryRequest,
  loadDocs, loadForgottenDocs, loadOverview, addMemory, updateDoc, softForgetDoc, restoreDoc, queryMemory, queryRawRag,
} = useMemoryDomain()
const e2eMode = Boolean(window.petApi?.e2e)
const sessionStore = useSessionStore()
const workspaceStore = useWorkspaceStore()
const activeWorkspace = computed(() => workspaceStore.activeWorkspace)
const normalizeMemoryScope = (scope?: string | null): MemoryScope => {
  if (scope === 'global' || scope === 'session') return scope
  return 'workspace'
}
const currentMemoryScope = computed<MemoryScope>(() => normalizeMemoryScope(activeWorkspace.value?.memory_scope))
const indexStatus = ref<MemoryIndexStatus | null>(null)
const retrievalStrategy = ref<{ label: string; layers: string[] }>({ label: '', layers: [] })
const advancedToolsVisible = ref(false)
const activeTab = ref<MemoryTab>('library')
const searchText = ref('')
const filterLayer = ref('')
const duplicateCandidates = ref<MemoryDuplicateCandidate[]>([])
const docViewMode = ref<DocViewMode>('all')
const docSortMode = ref<DocSortMode>('updated')
const selectedDocId = ref('')
const selectedQueryLayers = ref<string[]>([])
const form = reactive({ text: '', type: 'chat', layer: 'working', importance: 0.6, confidence: 0.86, source: 'manual' })
const docForm = reactive({ id: '', text: '', metadataJson: '' })
const queryForm = reactive({ query: '', scope: currentMemoryScope.value, top_k: 5 })
const editDialogVisible = ref(false)
const editForm = reactive({ id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual', metadataJson: '' })
const inspectorDraft = reactive({
  id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual',
  validFrom: '', validTo: '', expiresAt: '',
})
const docWriteLoading = ref(false)
const rebuildIndexLoading = ref(false)
const batchActionLoading = ref(false)
const workspaceScopeSaving = ref(false)
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

const layers = [
  { value: 'profile', label: '偏好与称呼', desc: '稳定偏好', color: 'purple' },
  { value: 'working', label: '当下任务', desc: '当前上下文', color: 'blue' },
  { value: 'episodic', label: '最近事件', desc: '具体事件', color: 'amber' },
  { value: 'relationship', label: '关系线索', desc: '陪伴线索', color: 'pink' },
  { value: 'reflective', label: '她的反思', desc: '反思总结', color: 'emerald' },
  { value: 'semantic', label: '长期事实', desc: '全局知识', color: 'slate' },
]

const memoryTypePresets = [
  { value: 'fact', label: '事实' },
  { value: 'preference', label: '偏好' },
  { value: 'event', label: '事件' },
  { value: 'promise', label: '承诺' },
  { value: 'taboo', label: '禁忌' },
  { value: 'summary', label: '摘要' },
]

const memoryScopeOptions: Array<{ value: MemoryScope; label: string }> = [
  { value: 'global', label: '全局' },
  { value: 'workspace', label: '工作区' },
  { value: 'session', label: '会话' },
]

const memorySourceOptions = [
  { value: 'manual', label: '手动录入' },
  { value: 'session', label: '对话片段' },
  { value: 'relationship', label: '关系观察' },
  { value: 'reflection', label: '反思总结' },
  { value: 'import', label: '资料导入' },
  { value: 'profile', label: '画像资料' },
]

const docViewOptions: Array<{ value: DocViewMode; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'recallable', label: '可召回' },
  { value: 'review', label: '待复核' },
  { value: 'important', label: '高重要度' },
  { value: 'hits', label: '本次命中' },
]

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
  if (!raw) return '未记录时间'
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
    global: '全局',
    workspace: '工作区',
    session: '会话',
  }
  return map[String(scope || '')] || String(scope || '工作区')
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
  stale_working: '超过工作记忆期限',
  low_quality: '质量低于阈值',
  exact_duplicate: '与保留项完全重复',
}[reason] || reason)).join('、')

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
    ElMessage.success('记忆整理规则已保存')
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
    ElMessage.error(error instanceof Error ? error.message : '无法预览记忆整理结果')
  } finally {
    maintenancePreviewLoading.value = false
  }
}

const applyMemoryMaintenance = async () => {
  if (maintenanceApplyLoading.value) return
  if (!maintenancePreviewMatchesPolicy.value) {
    ElMessage.warning('整理规则已变化，请重新预览影响后再执行')
    return
  }
  const previewToken = maintenancePreview.value?.preview_token
  if (!previewToken) {
    ElMessage.warning('请重新预览后再执行')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将永久清理 ${maintenancePreview.value?.summary.delete_count ?? 0} 条记忆，操作不可恢复。`,
      '永久清理记忆',
      { confirmButtonText: '永久清理', cancelButtonText: '取消', type: 'warning' },
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
    ElMessage.success(`已永久清理 ${result.changed_count} 条记忆`)
    await refreshMemoryState()
    try {
      maintenancePreview.value = await memoryClient.previewMaintenance(maintenancePayload())
      maintenancePreviewPolicyKey.value = maintenancePolicyKey()
    } catch {
      maintenancePreview.value = null
      maintenancePreviewPolicyKey.value = ''
      ElMessage.warning('整理已完成，但最新预览暂时无法刷新')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '记忆整理失败')
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
    ElMessage.success('记忆作用域已保存')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存记忆作用域失败')
  } finally {
    workspaceScopeSaving.value = false
  }
}


const recallableDocs = computed(() => docs.value)

const layerStats = computed(() => layers.map(layer => ({
  ...layer,
  count: overview.value?.by_layer[layer.value] ?? recallableDocs.value.filter(doc => doc.layer === layer.value).length,
})))
const queryTrace = computed(() => queryResult.value?.trace ?? null)
const queryHitIds = computed(() => new Set([
  ...(queryTrace.value?.selected_ids ?? []),
  ...((queryResult.value?.results ?? []).map(item => item.id).filter(Boolean)),
]))

const reviewDocs = computed(() => recallableDocs.value
  .filter(doc => Number(doc.confidence ?? 1) < 0.72 || Number(doc.quality_score ?? 1) < 0.66)
  .sort((left, right) => Math.min(Number(left.confidence ?? 1), Number(left.quality_score ?? 1)) - Math.min(Number(right.confidence ?? 1), Number(right.quality_score ?? 1))))
const memoryTabs = computed(() => [
  { value: 'library' as const, label: '记忆库', count: docs.value.length, icon: Collection, description: '搜索、添加和修正她当前可以使用的记忆。' },
  { value: 'review' as const, label: '待确认', count: reviewDocs.value.length, icon: User, description: '检查低置信度或质量较低的内容，避免错误延续。' },
  { value: 'overview' as const, label: '概览', icon: DataAnalysis, description: '查看范围、分层、活动和已停止召回的内容。' },
])

const activeTabMeta = computed(() => memoryTabs.value.find(tab => tab.value === activeTab.value) || memoryTabs.value[0])

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

const selectedLayerDefinition = computed(() => layers.find(layer => layer.value === form.layer) || layers[1])

const indexUiStatus = computed(() => getMemoryIndexUiStatus(indexStatus.value, docsRequest.loading))
const indexStatusLabel = computed(() => indexUiStatus.value.label)
const indexAvailabilityLabel = computed(() => indexUiStatus.value.availabilityLabel)
const indexStatusTone = computed<TagType>(() => indexUiStatus.value.tone)

const querySummary = computed(() => {
  const results = queryResult.value?.results ?? []
  if (!results.length) return ''
  const best = Math.max(...results.map(item => Number(item.score ?? 0)))
  return `${results.length} 条命中 · 最高得分 ${best.toFixed(4)}`
})

const defaultQueryLayers = ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic']
const effectiveQueryLayers = computed(() => {
  if (selectedQueryLayers.value.length) return selectedQueryLayers.value
  return retrievalStrategy.value.layers.length ? retrievalStrategy.value.layers : defaultQueryLayers
})

const selectedTraceIds = computed(() => queryTrace.value?.selected_ids.slice(0, 8) ?? [])
const hiddenTraceIdCount = computed(() => Math.max(0, (queryTrace.value?.selected_ids.length ?? 0) - selectedTraceIds.value.length))
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
const hasDocFilters = computed(() => docViewMode.value !== 'all' || docSortMode.value !== 'updated' || Boolean(filterLayer.value) || Boolean(searchText.value.trim()))
const batchTargetDocs = computed(() => hasDocFilters.value ? filteredDocs.value : [])
const batchTargetCount = computed(() => batchTargetDocs.value.length)
const batchActionDisabled = computed(() => batchActionLoading.value || !hasDocFilters.value || batchTargetCount.value === 0)
const batchActionHint = computed(() => {
  if (!hasDocFilters.value) return '请先选择视图、层级或输入搜索词，再批量处理'
  if (batchTargetCount.value === 0) return '当前筛选结果为空'
  return `将处理当前筛选结果中的 ${batchTargetCount.value} 条记忆`
})
const batchDeleteLabel = computed(() => {
  if (batchDeleteProgress.active) return `删除中 ${batchDeleteProgress.done}/${batchDeleteProgress.total}`
  if (!hasDocFilters.value) return '先筛选再删除'
  return `永久删除筛选结果 (${batchTargetCount.value})`
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
  const result = await memoryClient.rollbackDoc(doc.id, revision)
  if (result?.status === 'rolled_back' || result?.status === 'updated' || result?.status === 'ok') {
    ElMessage.success(`已恢复到版本 ${revision}`)
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
  indexStatus.value = await memoryClient.getIndexStatus()
}

const refreshMemoryState = async () => {
  const options = scopedDocOptions()
  await Promise.all([
    loadDocs(options),
    loadOverview(options),
    loadForgottenDocs(options),
  ])
  if (e2eMode) return
  try {
    await refreshIndexStatus()
  } catch (error) {
    console.debug('[MemoryPanel] failed to refresh index status:', error)
  }
}

const rebuildMemoryIndex = async () => {
  if (rebuildIndexLoading.value) return
  rebuildIndexLoading.value = true
  try {
    const result = await memoryClient.rebuildIndex()
    const indexedCount = result.indexed_count ?? result.document_count
    ElMessage.success(indexedCount !== undefined ? `索引已重建：${indexedCount} 条` : '索引已重建')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重建索引失败')
  } finally {
    rebuildIndexLoading.value = false
  }
}

const submitMemory = async () => {
  if (!form.text.trim()) return
  duplicateCandidates.value = []
  const result = await addMemory({
    text: form.text.trim(),
    type: form.type || 'chat',
    layer: form.layer,
    importance: form.importance,
    confidence: form.confidence,
    confidence_source: form.source,
    metadata: {
      source: form.source,
    },
    scope: currentMemoryScope.value,
    session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
  })
  if (result?.skipped) {
    duplicateCandidates.value = normalizeDuplicateCandidates(result.duplicate_candidates)
    ElMessage.warning(result.reason === 'low_importance' ? '重要度低于阈值，后端已跳过写入' : result.reason || '记忆写入已跳过')
    return
  }
  if (result?.status === 'ok') { ElMessage.success('记忆块已注入'); form.text = ''; void refreshMemoryState() }
}

const parseJsonObject = (rawValue: string, label: string) => {
  const raw = rawValue.trim()
  if (!raw) return {}
  const parsed: unknown = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object`)
  }
  return parsed as Record<string, unknown>
}

const parseMetadata = () => parseJsonObject(docForm.metadataJson, 'Metadata')

const submitDocument = async () => {
  if (!docForm.text.trim()) return
  docWriteLoading.value = true
  duplicateCandidates.value = []
  try {
    const documentText = docForm.text.trim()
    const metadata = parseMetadata()
    const scopedMetadata = {
      layer: 'semantic',
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      ...metadata,
    }
    const result = await memoryClient.addDoc({
      id: docForm.id.trim() || undefined,
      text: documentText,
      metadata: scopedMetadata,
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,

      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      layer: typeof scopedMetadata.layer === 'string' ? scopedMetadata.layer : undefined,
    })
    if (result.skipped) {
      duplicateCandidates.value = normalizeDuplicateCandidates(result.duplicate_candidates)
      ElMessage.warning(result.reason || '发现相似文档，已返回合并候选')
      return
    }
    ElMessage.success(`文档已写入：${result.id}`)
    docForm.id = ''
    docForm.text = ''
    docForm.metadataJson = ''
    if (e2eMode) {
      const createdMetadata = scopedMetadata as Record<string, unknown>
      docs.value = [{
        id: result.id,
        text: documentText,
        type: typeof createdMetadata.type === 'string' ? createdMetadata.type : 'fact',
        layer: typeof createdMetadata.layer === 'string' ? createdMetadata.layer : 'semantic',
        importance: Number.isFinite(Number(createdMetadata.importance)) ? Number(createdMetadata.importance) : undefined,
        confidence: Number.isFinite(Number(createdMetadata.confidence)) ? Number(createdMetadata.confidence) : undefined,
        updated_at: typeof createdMetadata.updated_at === 'string' ? createdMetadata.updated_at : undefined,
        source: typeof createdMetadata.source === 'string' ? createdMetadata.source : undefined,
        scope: typeof createdMetadata.scope === 'string' ? createdMetadata.scope : currentMemoryScope.value,
        expires_at: typeof createdMetadata.expires_at === 'string' ? createdMetadata.expires_at : undefined,
        metadata: createdMetadata,
      }, ...docs.value.filter(doc => doc.id !== result.id)]
      selectedDocId.value = result.id
    } else {
      void refreshMemoryState()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '写入文档失败')
  } finally {
    docWriteLoading.value = false
  }
}

const submitQuery = async () => {
  if (!queryForm.query.trim()) return
  await queryMemory({
    query: queryForm.query.trim(),
    top_k: queryForm.top_k,
    session_id: queryForm.scope === 'session' ? sessionStore.activeSession?.id : undefined,
    scope: queryForm.scope,
    layers: selectedQueryLayers.value.length ? effectiveQueryLayers.value : undefined,
  })
}

const submitRawQuery = async () => {
  if (!queryForm.query.trim()) return
  await queryRawRag({
    query: queryForm.query.trim(),
    top_k: queryForm.top_k,
    session_id: queryForm.scope === 'session' ? sessionStore.activeSession?.id : undefined,
    scope: queryForm.scope,
    layers: effectiveQueryLayers.value,
  })
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
    ElMessage.warning('未找到要纠正的记忆')
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
    `已移动到 ${layer}`,
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
    '重要度已提高',
  )
}

const batchUpdateVisibleDocs = async (
  actionLabel: string,
  buildOverrides: (doc: MemoryDoc) => Parameters<typeof buildDocUpdatePayload>[1],
) => {
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info('请先选择视图、层级或搜索词，再批量处理')
    return
  }
  if (!targets.length) return
  try {
    await ElMessageBox.confirm(
      `将对当前筛选结果中的 ${targets.length} 条记忆执行“${actionLabel}”。`,
      '批量整理记忆',
      {
        confirmButtonText: actionLabel,
        cancelButtonText: '取消',
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
    ElMessage.success(`已处理 ${targets.length} 条记忆`)
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量整理失败')
  } finally {
    batchActionLoading.value = false
  }
}

const batchBoostVisibleDocs = () => batchUpdateVisibleDocs('提高重要度', doc => ({
  importance: Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85)),
  edit_reason: 'batch_boost_importance',
}))

const batchDeleteVisibleDocs = async () => {
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info('请先选择视图、层级或搜索词，再批量删除')
    return
  }
  if (!targets.length) return
  const targetIds = new Set(targets.map(doc => doc.id))
  const ids = [...targetIds]
  const previousDocs = docs.value.slice()
  const previousSelectedDocId = selectedDocId.value
  const nextSelectedId = docs.value.find(doc => !targetIds.has(doc.id))?.id || ''
  try {
    await ElMessageBox.confirm(
      '这些记忆将从存储中永久删除。',
      `永久删除 ${targets.length} 条记忆`,
      {
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
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
    const result = await memoryClient.removeDocs(ids)
    batchDeleteProgress.done = result.deleted_count ?? ids.length
    ElMessage.success(`已永久删除 ${batchDeleteProgress.done} 条记忆`)
    await refreshIndexStatus().catch(error => console.debug('[MemoryPanel] failed to refresh index status after batch delete:', error))
  } catch (error) {
    docs.value = previousDocs
    selectedDocId.value = previousSelectedDocId
    ElMessage.error(error instanceof Error ? error.message : '批量删除失败')
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
      ElMessage.success('记忆已更新')
      editDialogVisible.value = false
      selectedDocId.value = editForm.id
      void refreshMemoryState()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新记忆失败')
  }
}

const removeDoc = async (id: string) => {
  if (removingDocIds.value.has(id)) return
  try {
    await ElMessageBox.confirm(
      '这条记忆将从存储中永久删除。',
      '永久删除记忆',
      {
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',

        type: 'warning',
      },
    )
  } catch {
    return
  }

  setDocRemoving(id, true)
  try {
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    await memoryClient.removeDoc(id)
    ElMessage.success('已永久删除这条记忆')
    if (selectedDocId.value === id) selectedDocId.value = fallbackId
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '永久删除失败')
  } finally {
    setDocRemoving(id, false)
  }
}

const forgetDoc = async (id: string) => {
  if (forgettingDocIds.value.has(id)) return
  try {
    await ElMessageBox.confirm(
      '停止召回后，这条记忆不会再参与回答；你仍可在概览中恢复。',
      '停止召回这条记忆',
      { confirmButtonText: '停止召回', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  setPendingDocId(forgettingDocIds, id, true)
  try {
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    await softForgetDoc(id, { reason: 'user_soft_forget' })
    if (selectedDocId.value === id) selectedDocId.value = fallbackId
    ElMessage.success('已停止召回这条记忆')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '停止召回失败')
  } finally {
    setPendingDocId(forgettingDocIds, id, false)
  }
}

const restoreForgottenDoc = async (id: string) => {
  if (restoringDocIds.value.has(id)) return
  setPendingDocId(restoringDocIds, id, true)
  try {
    await restoreDoc(id, { reason: 'user_restore' })
    ElMessage.success('这条记忆已恢复召回')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复召回失败')
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
    manual: '手动',
    session: '会话',
    relationship: '关系',
    reflection: '反思',
    import: '导入',
    profile: '画像',
    default: '默认',
    explicit: '显式',
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
      '记忆已保存',
    )
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存记忆失败')
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
    create: '创建',
    update: '更新',
  }
  const key = String(value || 'event')
  return map[key] || key
}

const auditEntrySummary = (entry: Record<string, unknown>) => {
  const at = typeof entry.at === 'string' ? entry.at.replace('T', ' ').slice(0, 16) : ''
  const reason = typeof entry.reason === 'string' ? entry.reason : ''
  return [at, reason].filter(Boolean).join(' · ') || '无时间'
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

onMounted(async () => {
  queryForm.scope = currentMemoryScope.value
  await refreshMemoryState()
  openRequestedMemoryDoc()
  if (e2eMode) return
  try {
    const payload = await systemClient.companionRuntime(4)
    if (payload.retrieval_strategy) {
      retrievalStrategy.value = {
        label: payload.retrieval_strategy.label || '',
        layers: payload.retrieval_strategy.layers || [],
      }
    }
  } catch (error) {
    console.debug('[MemoryPanel] failed to load retrieval strategy:', error)
  }
})
</script>


<style scoped>
.memory-panel { display: flex; min-height: 0; flex-direction: column; gap: 14px; }
.local-status { color: var(--yui-muted); font-size: 11px; }
.scope-control { display: flex; align-items: center; gap: 7px; color: var(--yui-muted); font-size: 11px; }
.scope-control :deep(.el-select) { width: 108px; }
.memory-welcome { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 18px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: color-mix(in srgb, var(--yui-accent-soft) 58%, var(--yui-surface)); }
.welcome-copy { min-width: 0; }
.welcome-kicker { display: inline-flex; align-items: center; gap: 5px; color: var(--yui-accent); font-size: 11px; font-weight: 700; }
.welcome-copy h3 { margin: 5px 0 4px; color: var(--yui-text); font-size: 17px; line-height: 1.3; }
.welcome-copy p { max-width: 58ch; margin: 0; color: var(--yui-muted); font-size: 12px; line-height: 1.55; }
.memory-health { display: flex; flex: 0 0 auto; align-items: stretch; gap: 8px; }
.scope-pill, .health-stat { display: flex; min-width: 72px; flex-direction: column; justify-content: center; gap: 3px; padding: 8px 10px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-control); background: color-mix(in srgb, var(--yui-surface) 80%, transparent); }
.scope-pill span, .health-stat span { color: var(--yui-muted); font-size: 10px; }
.scope-pill strong, .health-stat strong { color: var(--yui-text); font-size: 13px; }
.health-stat.attention { border-color: color-mix(in srgb, #d97706 42%, var(--yui-border)); background: var(--yui-warning-soft); }
.memory-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--yui-border); }
.memory-tabs button { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 8px 14px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--yui-muted); font: inherit; font-size: 13px; cursor: pointer; }
.memory-tabs button[aria-selected="true"] { border-bottom-color: var(--yui-accent); color: var(--yui-text); font-weight: 700; }
.memory-tabs button .tab-count { display: inline-grid; min-width: 18px; min-height: 18px; margin-left: 2px; place-items: center; border-radius: 9px; background: var(--yui-surface-muted); font-size: 10px; }
.memory-tabs button[aria-selected="true"] .tab-count { background: var(--yui-accent-soft); color: var(--yui-accent); }
.memory-tabs button:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: -2px; }
.tab-context { display: flex; align-items: baseline; gap: 8px; min-height: 18px; color: var(--yui-muted); font-size: 12px; }
.tab-context strong { color: var(--yui-text); font-size: 12px; }
.tab-panel { min-width: 0; }
.tab-panel > :deep(* + *) { margin-top: 18px; }
.dialog-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.dialog-grid :deep(.el-select), :deep(.el-dialog .el-select) { width: 100%; }
details summary { margin-bottom: 10px; color: var(--yui-muted); cursor: pointer; font-size: 12px; }
@media (max-width: 760px) { .scope-control span { display: none; }.memory-welcome { align-items: stretch; flex-direction: column; gap: 12px; }.memory-health { width: 100%; }.scope-pill, .health-stat { flex: 1; }.memory-tabs { position: sticky; top: 0; z-index: 2; background: var(--yui-panel-surface, var(--yui-surface)); }.memory-tabs button { flex: 1; justify-content: center; padding-inline: 8px; }.tab-context { align-items: flex-start; flex-direction: column; gap: 2px; }.dialog-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; } }
</style>

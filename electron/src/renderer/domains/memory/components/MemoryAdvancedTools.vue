<template>
  <div class="advanced-tools">
    <section>
      <div class="section-head"><div><h3>{{ t('memoryView.searchStatusTitle') }}</h3></div><el-tag :type="indexStatusTone">{{ indexStatusLabel }}</el-tag></div>
      <dl><div><dt>{{ t('memoryView.saved') }}</dt><dd>{{ docCount }}</dd></div><div><dt>{{ t('memoryView.indexCount') }}</dt><dd>{{ indexStatus?.count ?? '-' }}</dd></div><div><dt>{{ t('memoryView.searchStatusTitle') }}</dt><dd>{{ indexAvailabilityLabel }}</dd></div></dl>
      <p v-if="indexStatus?.message" class="status-text" role="status">{{ indexStatus.message }}</p>
      <div v-if="rebuildActive" class="rebuild-progress" role="status">
        <el-progress :percentage="rebuildProgress" :stroke-width="8" />
        <span>{{ rebuildProgressText }}</span>
      </div>
      <p v-else-if="rebuildJob?.last_error" class="status-text rebuild-error" role="alert">{{ rebuildJob.last_error }}</p>
      <div class="button-row">
        <el-button plain :loading="rebuildIndexLoading" :disabled="rebuildActive" @click="emit('rebuild-index')">{{ rebuildJob?.recoverable ? t('memoryView.rebuildIndexRecoverable') : t('memoryView.rebuildIndex') }}</el-button>
        <el-button v-if="rebuildActive" plain type="warning" @click="emit('cancel-rebuild-index')">{{ t('memoryView.cancelRebuild') }}</el-button>
      </div>
    </section>

    <section>
      <div class="section-head"><h3>{{ t('memoryView.querySectionTitle') }}</h3><el-tag v-if="querySummary" type="success">{{ querySummary }}</el-tag></div>
      <el-form label-position="top" @submit.prevent="emit('query')">
        <el-form-item :label="t('memoryView.queryLabel')"><el-input :model-value="queryForm.query" data-testid="memory-query-input" :placeholder="t('memoryView.queryPlaceholder')" @update:model-value="updateQuery('query', String($event))" @keyup.enter="emit('query')" /></el-form-item>
        <div class="form-grid"><el-form-item :label="t('memoryView.queryScopeLabel')"><el-select :model-value="queryForm.scope" @update:model-value="updateQuery('scope', $event as MemoryQueryForm['scope'])"><el-option :label="t('memoryView.scopeAllWorkspaces')" value="global"/><el-option :label="t('memoryView.scopeWorkspace')" value="workspace"/><el-option :label="t('memoryView.scopeSession')" value="session"/></el-select></el-form-item><el-form-item :label="t('memoryView.queryTopKLabel')"><el-input-number :model-value="queryForm.top_k" :min="1" :max="20" @update:model-value="updateQuery('top_k', Number($event))" /></el-form-item></div>
        <div class="relation-controls"><label><el-switch :model-value="queryForm.expand_relations" @update:model-value="updateQuery('expand_relations', Boolean($event))" />{{ t('memoryView.queryExpandRelations') }}</label><label v-if="queryForm.expand_relations"><span>{{ t('memoryView.queryRelationLimit', { count: queryForm.relation_limit }) }}</span><el-slider :model-value="queryForm.relation_limit" :min="1" :max="100" :step="1" @update:model-value="updateQuery('relation_limit', Number($event))" /></label><label v-if="queryForm.expand_relations" class="depth-control"><span>{{ t('memoryView.queryRelationDepth') }}</span><el-input-number :model-value="queryForm.relation_depth" :min="1" :max="3" size="small" @update:model-value="updateQuery('relation_depth', Number($event))" /></label></div>
        <div class="layer-picker" :aria-label="t('memoryView.queryLayersAria')"><button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="effectiveQueryLayers.includes(layer.value)" @click="emit('toggle-query-layer', layer.value)">{{ layer.label }}</button></div>
        <div class="button-row"><el-button data-testid="memory-query-submit" type="primary" native-type="submit" :loading="queryLoading" :disabled="!queryForm.query.trim()">{{ t('memoryView.querySubmit') }}</el-button><el-button link type="primary" @click="emit('reset-query-layers')">{{ t('memoryView.queryAllLayers') }}</el-button></div>
      </el-form>
      <details v-if="queryTrace" class="trace-details"><summary>{{ t('memoryView.queryTraceSummary') }}</summary><div class="trace" role="status"><span>{{ t('memoryView.queryTraceFound', { count: queryTrace.recall_count ?? queryResult?.results?.length ?? 0, latency: formatLatency(queryTrace.latency_ms) }) }}</span><span>{{ t('memoryView.queryTraceRelated', { count: queryTrace.expanded_ids?.length ?? 0, percent: Math.round((queryTrace.evidence_coverage ?? 0) * 100) }) }}</span><span v-if="queryTrace.expansion_truncated">{{ t('memoryView.queryTraceTruncated') }}</span><span v-if="filterReasonText">{{ filterReasonText }}</span><code v-if="selectedTraceIds.length">{{ selectedTraceIds.join(' · ') }}<template v-if="hiddenTraceIdCount"> +{{ hiddenTraceIdCount }}</template></code></div></details>
      <AsyncState :loading="queryLoading" :error="queryError" :empty="!queryResult?.results?.length" :empty-text="t('memoryView.queryEmpty')" :show-retry="false"><div class="results" data-testid="memory-query-results"><article v-for="(row,index) in queryResult?.results || []" :key="row.id || index" :data-memory-query-id="row.id || undefined"><b>{{ index + 1 }}</b><div><p>{{ row.text }}</p><span>{{ t('memoryView.relevance', { percent: scorePercent(row.score) }) }}</span><div v-if="row.why_recalled || row.evidence_type" class="recall-explanation"><strong>{{ row.why_recalled || t('memoryView.relevanceFallback') }}</strong><small v-if="row.evidence_type">{{ evidenceTypeLabel(row.evidence_type) }}<template v-if="row.association"> · {{ row.association }}</template><template v-if="helpfulRecallCount(row)"> · {{ t('memoryView.helpfulCount', { count: helpfulRecallCount(row) }) }}</template></small></div><div v-if="row.id" class="result-actions"><el-button link type="primary" @click="emit('select-result', row.id)">{{ t('memoryView.viewMemory') }}</el-button><div class="feedback-row" role="group" :aria-label="t('memoryView.recallFeedbackAria')"><el-button size="small" plain :type="feedbackFor(row.id) === 'helpful' ? 'success' : undefined" @click="sendFeedback(row.id, 'helpful')">{{ t('memoryView.feedbackHelpful') }}</el-button><el-button size="small" plain :type="feedbackFor(row.id) === 'not_helpful' ? 'warning' : undefined" @click="sendFeedback(row.id, 'not_helpful')">{{ t('memoryView.feedbackNotHelpful') }}</el-button><el-button size="small" plain :type="feedbackFor(row.id) === 'incorrect' ? 'danger' : undefined" @click="sendFeedback(row.id, 'incorrect')">{{ t('memoryView.feedbackIncorrect') }}</el-button><el-button size="small" link :type="feedbackFor(row.id) === 'dismissed' ? 'info' : undefined" @click="sendFeedback(row.id, 'dismissed')">{{ t('memoryView.feedbackDismissed') }}</el-button></div></div></div></article></div></AsyncState>
    </section>

    <details class="maintenance-section">
      <summary><strong>{{ t('memoryView.maintenanceTitle') }}</strong><el-tag data-testid="memory-maintenance-summary" :type="maintenancePreview?.summary.delete_count ? 'danger' : 'info'">{{ maintenancePreview ? t('memoryView.maintenancePending', { count: maintenancePreview.summary.delete_count }) : t('memoryView.maintenanceNotPreviewed') }}</el-tag></summary>
      <section>
        <div class="form-grid"><label><span>{{ t('memoryView.maintenanceWorkingDays') }}</span><el-input-number :model-value="maintenancePolicy.workingRetentionDays" :min="1" :max="365" @update:model-value="updateMaintenance('workingRetentionDays', Number($event))" /></label><label><span>{{ t('memoryView.maintenanceQualityThreshold', { percent: Math.round(maintenancePolicy.lowQualityThreshold*100) }) }}</span><el-slider :model-value="maintenancePolicy.lowQualityThreshold" :min="0" :max="1" :step="0.05" @update:model-value="updateMaintenance('lowQualityThreshold', Number($event))" /></label></div>
        <div class="switches"><label><el-switch :model-value="maintenancePolicy.includeStaleWorking" @update:model-value="updateMaintenance('includeStaleWorking', Boolean($event))" />{{ t('memoryView.maintenanceStaleWorking') }}</label><label><el-switch :model-value="maintenancePolicy.includeLowQuality" @update:model-value="updateMaintenance('includeLowQuality', Boolean($event))" />{{ t('memoryView.maintenanceLowQuality') }}</label><label><el-switch :model-value="maintenancePolicy.includeExactDuplicates" @update:model-value="updateMaintenance('includeExactDuplicates', Boolean($event))" />{{ t('memoryView.maintenanceDuplicates') }}</label></div>
        <div class="button-row"><el-button plain :loading="maintenanceSaving" @click="emit('save-maintenance')">{{ t('memoryView.maintenanceSave') }}</el-button><el-button data-testid="memory-maintenance-preview" type="primary" plain :loading="maintenancePreviewLoading" @click="emit('preview-maintenance')">{{ t('memoryView.maintenancePreview') }}</el-button><el-button type="danger" :loading="maintenanceApplyLoading" :disabled="!maintenancePreview?.summary.delete_count || !maintenancePreviewMatchesPolicy" @click="emit('apply-maintenance')">{{ t('memoryView.deleteForever') }}</el-button></div>
        <div v-if="maintenancePreview?.candidates.length" class="candidates"><article v-for="candidate in maintenancePreview.candidates.slice(0,8)" :key="candidate.id"><span>{{ compactText(candidate.text,70) || candidate.id }}</span><b>{{ maintenanceReasonLabel(candidate.reasons) }}</b></article></div>
      </section>
    </details>
  </div>
</template>
<script setup lang="ts">
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/switch/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { computed, reactive } from 'vue'
import {
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  ElProgress,
  ElSelect,
  ElOption,
  ElSlider,
  ElSwitch,
  ElTag,
} from 'element-plus'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/progress/style/css'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { t } from '@/i18n'
import type { MemoryIndexStatus, MemoryLayer, MemoryMaintenancePolicy, MemoryMaintenancePreview, MemoryQueryForm, TagType } from './memory-panel-types'
import type { MemoryIndexRebuildJob, MemoryRecallFeedback } from '@/api/clients/memory-client'
import type { MemoryQueryResult, MemoryRetrievalTrace } from '../composables/useMemoryDomain'
const props=defineProps<{ indexStatus:MemoryIndexStatus|null; rebuildJob:MemoryIndexRebuildJob|null; indexStatusLabel:string; indexAvailabilityLabel:string; indexStatusTone:TagType; docCount:number; rebuildIndexLoading:boolean; queryForm:MemoryQueryForm; layers:MemoryLayer[]; effectiveQueryLayers:string[]; queryLoading:boolean; queryError?:string; queryResult:MemoryQueryResult|null; querySummary:string; filterReasonText:string; maintenancePolicy:MemoryMaintenancePolicy; maintenancePreview:MemoryMaintenancePreview|null; maintenancePreviewMatchesPolicy:boolean; maintenanceSaving:boolean; maintenancePreviewLoading:boolean; maintenanceApplyLoading:boolean; formatLatency:(value?:number|null)=>string; compactText:(text?:string|null,limit?:number)=>string; maintenanceReasonLabel:(reasons:string[])=>string }>()
const emit=defineEmits<{ 'rebuild-index':[];'cancel-rebuild-index':[];query:[];'toggle-query-layer':[layer:string];'reset-query-layers':[];'select-result':[id:string];feedback:[payload:{id:string;feedback:MemoryRecallFeedback}];'save-maintenance':[];'preview-maintenance':[];'apply-maintenance':[];'update-query':[value:Partial<MemoryQueryForm>];'update-maintenance':[value:Partial<MemoryMaintenancePolicy>] }>()
const queryTrace = computed<MemoryRetrievalTrace | null>(() => props.queryResult?.trace ?? null)
const selectedTraceIds = computed(() => queryTrace.value?.selected_ids.slice(0, 8) ?? [])
const hiddenTraceIdCount = computed(() => Math.max(0, (queryTrace.value?.selected_ids.length ?? 0) - selectedTraceIds.value.length))
const rebuildActive = computed(() => ['queued', 'running', 'cancelling'].includes(props.rebuildJob?.state || ''))
const rebuildProgress = computed(() => {
  const total = props.rebuildJob?.total_count || 0
  if (!total) return props.rebuildJob?.state === 'completed' ? 100 : 0
  return Math.min(100, Math.round(((props.rebuildJob?.processed_count || 0) / total) * 100))
})
const rebuildProgressText = computed(() => {
  const job = props.rebuildJob
  if (!job) return ''
  if (job.state === 'cancelling') return t('memoryView.rebuildCancelling')
  return t('memoryView.rebuildProgress', { processed: job.processed_count, total: job.total_count })
})
const updateQuery = <K extends keyof MemoryQueryForm>(key: K, value: MemoryQueryForm[K]) => emit('update-query', { [key]: value })
const updateMaintenance = <K extends keyof MemoryMaintenancePolicy>(key: K, value: MemoryMaintenancePolicy[K]) => emit('update-maintenance', { [key]: value })
const scorePercent = (value: unknown) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%` : '-'
}
const feedbackById = reactive<Record<string, MemoryRecallFeedback>>({})
const feedbackFor = (id: string) => feedbackById[id]
const sendFeedback = (id: string, feedback: MemoryRecallFeedback) => {
  feedbackById[id] = feedback
  emit('feedback', { id, feedback })
}
const evidenceTypeLabels = computed<Record<string, string>>(() => ({
  anchor: t('memoryView.evidenceAnchor'),
  relation: t('memoryView.evidenceRelation'),
  ranking: t('memoryView.evidenceRanking'),
  source: t('memoryView.evidenceSource'),
}))
const evidenceTypeLabel = (value: string) => evidenceTypeLabels.value[value] || value
const helpfulRecallCount = (row: { metadata?: Record<string, unknown> }) => {
  const feedback = row.metadata?.recall_feedback
  if (!feedback || typeof feedback !== 'object' || Array.isArray(feedback)) return 0
  const summary = (feedback as Record<string, unknown>).summary
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return 0
  const count = Number((summary as Record<string, unknown>).helpful)
  return Number.isFinite(count) && count > 0 ? count : 0
}
</script>
<style scoped>
.advanced-tools { display:flex;flex-direction:column;gap:24px; }.advanced-tools section { display:flex;flex-direction:column;gap:14px;padding-bottom:22px;border-bottom:1px solid var(--yui-border); }.section-head,.button-row { display:flex;align-items:flex-start;justify-content:space-between;gap:12px; }.section-head h3 { margin:0;color:var(--yui-text);font-size:15px; }.section-head p,.status-text { margin:4px 0 0;color:var(--yui-muted);font-size:12px;line-height:1.5; }dl { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0; }dl div { padding:10px;background:var(--yui-surface-muted);border-radius:var(--yui-radius-control); }dt { color:var(--yui-muted);font-size:11px; }dd { margin:4px 0 0;color:var(--yui-text);font-weight:700; }.form-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px; }.form-grid>label { display:flex;flex-direction:column;gap:8px;color:var(--yui-muted);font-size:12px; }.form-grid :deep(.el-select){width:100%;}.relation-controls { display:flex; flex-wrap:wrap; align-items:center; gap:14px; }.relation-controls label { display:flex; align-items:center; gap:7px; color:var(--yui-muted); font-size:12px; }.relation-controls label:last-child { min-width:180px; flex:1; flex-direction:column; align-items:stretch; gap:3px; }.layer-picker,.switches,.button-row { display:flex;flex-wrap:wrap;gap:8px; }.layer-picker button { min-height:30px;border:1px solid var(--yui-border);border-radius:var(--yui-radius-control);background:var(--yui-surface);color:var(--yui-text);cursor:pointer; }.layer-picker button[aria-pressed="true"]{border-color:var(--yui-accent);background:var(--yui-accent-soft);}.trace { display:flex;flex-direction:column;gap:5px;padding:10px;border-radius:var(--yui-radius-card);background:var(--yui-surface-muted);color:var(--yui-muted);font-size:11px; }.trace strong{color:var(--yui-text);}.trace code{overflow-wrap:anywhere}.results,.candidates{display:grid;gap:8px}.results article{display:grid;grid-template-columns:24px 1fr;gap:8px;padding:10px;border-bottom:1px solid var(--yui-border)}.results p{margin:0;color:var(--yui-text);font-size:12px}.results span{color:var(--yui-muted);font-size:11px}.recall-explanation{display:flex;flex-direction:column;gap:2px;margin-top:7px;padding:7px 9px;border-left:2px solid var(--yui-accent);background:var(--yui-accent-soft);}.recall-explanation strong{color:var(--yui-text);font-size:11px}.recall-explanation small{color:var(--yui-muted);font-size:10px}.result-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:7px}.feedback-row{display:flex;flex-wrap:wrap;gap:4px}.candidates article{display:flex;justify-content:space-between;gap:12px;padding:8px;background:var(--yui-danger-soft);border-radius:var(--yui-radius-control);font-size:11px}.switches label{display:flex;align-items:center;gap:5px;color:var(--yui-text);font-size:12px}
.rebuild-progress{display:grid;gap:6px}.rebuild-progress span,.rebuild-error{font-size:12px}.rebuild-error{color:var(--yui-danger)}
.maintenance-section{padding-bottom:22px;border-bottom:1px solid var(--yui-border)}.maintenance-section>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--yui-text);cursor:pointer;list-style:none}.maintenance-section>summary::-webkit-details-marker{display:none}.maintenance-section>summary>span{display:flex;min-width:0;flex-direction:column;gap:3px}.maintenance-section>summary strong{font-size:15px}.maintenance-section>summary small{color:var(--yui-muted);font-size:12px}.maintenance-section section{padding:14px 0 0;border-bottom:0}
@media(max-width:600px){.form-grid,dl{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}}
</style>

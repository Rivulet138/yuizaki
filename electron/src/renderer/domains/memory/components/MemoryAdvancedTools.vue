<template>
  <div class="advanced-tools">
    <section>
      <div class="section-head"><div><h3>搜索索引</h3><p>索引仅用于检索；原始文档保存在记忆库。</p></div><el-tag :type="indexStatusTone">{{ indexStatusLabel }}</el-tag></div>
      <dl><div><dt>文档</dt><dd>{{ docCount }}</dd></div><div><dt>索引</dt><dd>{{ indexStatus?.count ?? '-' }}</dd></div><div><dt>可用性</dt><dd>{{ indexAvailabilityLabel }}</dd></div></dl>
      <p v-if="indexStatus?.message" class="status-text" role="status">{{ indexStatus.message }}</p>
      <div v-if="rebuildActive" class="rebuild-progress" role="status">
        <el-progress :percentage="rebuildProgress" :stroke-width="8" />
        <span>{{ rebuildProgressText }}</span>
      </div>
      <p v-else-if="rebuildJob?.last_error" class="status-text rebuild-error" role="alert">{{ rebuildJob.last_error }}</p>
      <div class="button-row">
        <el-button plain :loading="rebuildIndexLoading" :disabled="rebuildActive" @click="emit('rebuild-index')">{{ rebuildJob?.recoverable ? '重新构建' : '重建索引' }}</el-button>
        <el-button v-if="rebuildActive" plain type="warning" @click="emit('cancel-rebuild-index')">取消重建</el-button>
      </div>
    </section>

    <section>
      <div class="section-head"><div><h3>召回实验台</h3><p>输入查询并查看召回结果、关联证据和分数。</p></div><el-tag v-if="querySummary" type="success">{{ querySummary }}</el-tag></div>
      <el-form label-position="top" @submit.prevent="emit('query')">
        <el-form-item label="查询文本"><el-input :model-value="queryForm.query" data-testid="memory-query-input" placeholder="输入要匹配的内容" @update:model-value="updateQuery('query', String($event))" @keyup.enter="emit('query')" /></el-form-item>
        <div class="form-grid"><el-form-item label="作用域"><el-select :model-value="queryForm.scope" @update:model-value="updateQuery('scope', $event as MemoryQueryForm['scope'])"><el-option label="全局" value="global"/><el-option label="工作区" value="workspace"/><el-option label="会话" value="session"/></el-select></el-form-item><el-form-item label="返回数量"><el-input-number :model-value="queryForm.top_k" :min="1" :max="20" @update:model-value="updateQuery('top_k', Number($event))" /></el-form-item></div>
        <div class="relation-controls"><label><el-switch :model-value="queryForm.expand_relations" @update:model-value="updateQuery('expand_relations', Boolean($event))" />扩展关联证据</label><label v-if="queryForm.expand_relations"><span>最多扩展 {{ queryForm.relation_limit }} 条</span><el-slider :model-value="queryForm.relation_limit" :min="1" :max="100" :step="1" @update:model-value="updateQuery('relation_limit', Number($event))" /></label><label v-if="queryForm.expand_relations" class="depth-control"><span>扩展深度</span><el-input-number :model-value="queryForm.relation_depth" :min="1" :max="3" size="small" @update:model-value="updateQuery('relation_depth', Number($event))" /></label></div>
        <div class="layer-picker" aria-label="检索层级"><button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="effectiveQueryLayers.includes(layer.value)" @click="emit('toggle-query-layer', layer.value)">{{ layer.label }}</button></div>
        <div class="button-row"><el-button data-testid="memory-query-submit" type="primary" native-type="submit" :loading="queryLoading" :disabled="!queryForm.query.trim()">执行检索</el-button><el-button data-testid="memory-raw-query-submit" plain :loading="rawQueryLoading" :disabled="!queryForm.query.trim()" @click="emit('raw-query')">执行原始查询</el-button><el-button link type="primary" @click="emit('reset-query-layers')">恢复默认层级</el-button></div>
      </el-form>
      <div v-if="queryTrace" class="trace" role="status"><strong>检索轨迹</strong><span>召回 {{ queryTrace.recall_count ?? queryResult?.results?.length ?? 0 }} · 候选 {{ queryTrace.candidate_count ?? 0 }} · 过滤 {{ queryTrace.filtered_out_count ?? 0 }} · {{ formatLatency(queryTrace.latency_ms) }}</span><span>锚点 {{ queryTrace.anchor_ids?.length ?? 0 }} · 关联 {{ queryTrace.expanded_ids?.length ?? 0 }} · 关联耗时 {{ formatLatency(queryTrace.relation_latency_ms) }}<template v-if="queryTrace.expansion_truncated"> · 已达到扩展上限</template></span><span>证据覆盖率 {{ Math.round((queryTrace.evidence_coverage ?? 0) * 100) }}% · 文本预算估算 {{ queryTrace.relation_token_estimate ?? 0 }} tokens</span><span v-if="filterReasonText">{{ filterReasonText }}</span><code v-if="selectedTraceIds.length">{{ selectedTraceIds.join(' · ') }}<template v-if="hiddenTraceIdCount"> +{{ hiddenTraceIdCount }}</template></code></div>
      <AsyncState :loading="queryLoading" :error="queryError" :empty="!queryResult?.results?.length" empty-text="暂无检索结果" @retry="emit('query')"><div class="results" data-testid="memory-query-results"><article v-for="(row,index) in queryResult?.results || []" :key="row.id || index" :data-memory-query-id="row.id || undefined"><b>{{ index + 1 }}</b><div><p>{{ row.text }}</p><span>得分 {{ Number(row.score ?? 0).toFixed(4) }}</span><div v-if="row.why_recalled || row.evidence_type" class="recall-explanation"><strong>{{ row.why_recalled || '按相关性排序进入结果' }}</strong><small v-if="row.evidence_type">{{ evidenceTypeLabel(row.evidence_type) }}<template v-if="row.association"> · {{ row.association }}</template><template v-if="helpfulRecallCount(row)"> · 已帮助 {{ helpfulRecallCount(row) }} 次</template></small></div><div class="score-components" aria-label="召回分数构成"><span v-for="component in scoreComponentRows(row.score_components, row.score)" :key="component.key"><small>{{ component.label }}</small><strong>{{ component.value }}</strong></span></div><div v-if="row.id" class="result-actions"><el-button link type="primary" @click="emit('select-result', row.id)">查看记忆</el-button><div class="feedback-row" role="group" aria-label="召回反馈"><el-button size="small" plain :type="feedbackFor(row.id) === 'helpful' ? 'success' : undefined" @click="sendFeedback(row.id, 'helpful')">有帮助</el-button><el-button size="small" plain :type="feedbackFor(row.id) === 'not_helpful' ? 'warning' : undefined" @click="sendFeedback(row.id, 'not_helpful')">没帮助</el-button><el-button size="small" plain :type="feedbackFor(row.id) === 'incorrect' ? 'danger' : undefined" @click="sendFeedback(row.id, 'incorrect')">不准确</el-button><el-button size="small" link :type="feedbackFor(row.id) === 'dismissed' ? 'info' : undefined" @click="sendFeedback(row.id, 'dismissed')">暂不评价</el-button></div></div></div></article></div></AsyncState>
    </section>

    <section>
      <div class="section-head"><div><h3>原始文档写入</h3><p>直接提交文档内容和元数据。</p></div></div>
<el-form label-position="top" @submit.prevent="emit('write-document')"><el-form-item label="文档 ID（可选）"><el-input :model-value="documentForm.id" @update:model-value="updateDocument('id', String($event))" /></el-form-item><el-form-item label="文档内容"><el-input :model-value="documentForm.text" data-testid="memory-document-text" type="textarea" :rows="4" @update:model-value="updateDocument('text', String($event))" /></el-form-item><el-form-item label="元数据 JSON"><el-input :model-value="documentForm.metadataJson" data-testid="memory-document-metadata" type="textarea" :rows="3" @update:model-value="updateDocument('metadataJson', String($event))" /></el-form-item><el-button data-testid="memory-document-submit" type="primary" plain native-type="submit" :loading="documentLoading" :disabled="!documentForm.text.trim()">写入原始文档</el-button></el-form>
    </section>

    <section>
      <div class="section-head"><div><h3>维护操作</h3><p>先预览影响，再从本机存储永久删除。</p></div><el-tag data-testid="memory-maintenance-summary" :type="maintenancePreview?.summary.delete_count ? 'danger' : 'info'">{{ maintenancePreview ? `${maintenancePreview.summary.delete_count} 条待清理` : '尚未预览' }}</el-tag></div>
      <div class="form-grid"><label><span>工作记忆保留天数</span><el-input-number :model-value="maintenancePolicy.workingRetentionDays" :min="1" :max="365" @update:model-value="updateMaintenance('workingRetentionDays', Number($event))" /></label><label><span>低质量阈值 {{ Math.round(maintenancePolicy.lowQualityThreshold*100) }}%</span><el-slider :model-value="maintenancePolicy.lowQualityThreshold" :min="0" :max="1" :step="0.05" @update:model-value="updateMaintenance('lowQualityThreshold', Number($event))" /></label></div>
      <div class="switches"><label><el-switch :model-value="maintenancePolicy.includeStaleWorking" @update:model-value="updateMaintenance('includeStaleWorking', Boolean($event))" />过期工作记忆</label><label><el-switch :model-value="maintenancePolicy.includeLowQuality" @update:model-value="updateMaintenance('includeLowQuality', Boolean($event))" />低质量记忆</label><label><el-switch :model-value="maintenancePolicy.includeExactDuplicates" @update:model-value="updateMaintenance('includeExactDuplicates', Boolean($event))" />完全重复项</label></div>
      <div class="button-row"><el-button plain :loading="maintenanceSaving" @click="emit('save-maintenance')">保存整理规则</el-button><el-button data-testid="memory-maintenance-preview" type="primary" plain :loading="maintenancePreviewLoading" @click="emit('preview-maintenance')">预览影响</el-button><el-button type="danger" :loading="maintenanceApplyLoading" :disabled="!maintenancePreview?.summary.delete_count || !maintenancePreviewMatchesPolicy" @click="emit('apply-maintenance')">永久清理</el-button></div>
      <div v-if="maintenancePreview?.candidates.length" class="candidates"><article v-for="candidate in maintenancePreview.candidates.slice(0,8)" :key="candidate.id"><span>{{ compactText(candidate.text,70) || candidate.id }}</span><b>{{ maintenanceReasonLabel(candidate.reasons) }}</b></article></div>
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, reactive } from 'vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import type { MemoryDocumentForm, MemoryIndexStatus, MemoryLayer, MemoryMaintenancePolicy, MemoryMaintenancePreview, MemoryQueryForm, MemoryScoreComponents, TagType } from './memory-panel-types'
import type { MemoryIndexRebuildJob, MemoryRecallFeedback } from '@/api/clients/memory-client'
const props=defineProps<{ indexStatus:MemoryIndexStatus|null; rebuildJob:MemoryIndexRebuildJob|null; indexStatusLabel:string; indexAvailabilityLabel:string; indexStatusTone:TagType; docCount:number; rebuildIndexLoading:boolean; queryForm:MemoryQueryForm; layers:MemoryLayer[]; effectiveQueryLayers:string[]; queryLoading:boolean; rawQueryLoading:boolean; queryError?:string; queryResult:any; queryTrace:any; querySummary:string; filterReasonText:string; selectedTraceIds:string[]; hiddenTraceIdCount:number; documentForm:MemoryDocumentForm; documentLoading:boolean; maintenancePolicy:MemoryMaintenancePolicy; maintenancePreview:MemoryMaintenancePreview|null; maintenancePreviewMatchesPolicy:boolean; maintenanceSaving:boolean; maintenancePreviewLoading:boolean; maintenanceApplyLoading:boolean; formatLatency:(value?:number|null)=>string; compactText:(text?:string|null,limit?:number)=>string; maintenanceReasonLabel:(reasons:string[])=>string }>()
const emit=defineEmits<{ 'rebuild-index':[];'cancel-rebuild-index':[];query:[];'raw-query':[];'toggle-query-layer':[layer:string];'reset-query-layers':[];'select-result':[id:string];feedback:[payload:{id:string;feedback:MemoryRecallFeedback}];'write-document':[];'save-maintenance':[];'preview-maintenance':[];'apply-maintenance':[];'update-query':[value:Partial<MemoryQueryForm>];'update-document':[value:Partial<MemoryDocumentForm>];'update-maintenance':[value:Partial<MemoryMaintenancePolicy>] }>()
const rebuildActive = computed(() => ['queued', 'running', 'cancelling'].includes(props.rebuildJob?.state || ''))
const rebuildProgress = computed(() => {
  const total = props.rebuildJob?.total_count || 0
  if (!total) return props.rebuildJob?.state === 'completed' ? 100 : 0
  return Math.min(100, Math.round(((props.rebuildJob?.processed_count || 0) / total) * 100))
})
const rebuildProgressText = computed(() => {
  const job = props.rebuildJob
  if (!job) return ''
  if (job.state === 'cancelling') return '正在取消，已完成的索引不会丢失'
  return `已处理 ${job.processed_count}/${job.total_count}`
})
const updateQuery = <K extends keyof MemoryQueryForm>(key: K, value: MemoryQueryForm[K]) => emit('update-query', { [key]: value })
const updateDocument = <K extends keyof MemoryDocumentForm>(key: K, value: MemoryDocumentForm[K]) => emit('update-document', { [key]: value })
const updateMaintenance = <K extends keyof MemoryMaintenancePolicy>(key: K, value: MemoryMaintenancePolicy[K]) => emit('update-maintenance', { [key]: value })
const scoreComponentRows = (components?: MemoryScoreComponents, fallbackFinal?: number) => {
  const values: Array<{ key: keyof MemoryScoreComponents; label: string }> = [
    { key: 'semantic', label: '语义' },
    { key: 'lexical', label: '词法' },
    { key: 'recency', label: '时效' },
    { key: 'quality', label: '质量' },
    { key: 'learned', label: '学习' },
    { key: 'final', label: '最终' },
  ]
  return values.map(({ key, label }) => {
    const raw = key === 'final' ? components?.final ?? fallbackFinal : components?.[key]
    const numeric = Number(raw)
    return { key, label, value: Number.isFinite(numeric) ? numeric.toFixed(4) : '-' }
  })
}
const feedbackById = reactive<Record<string, MemoryRecallFeedback>>({})
const feedbackFor = (id: string) => feedbackById[id]
const sendFeedback = (id: string, feedback: MemoryRecallFeedback) => {
  feedbackById[id] = feedback
  emit('feedback', { id, feedback })
}
const evidenceTypeLabel = (value: string) => ({ anchor: '直接匹配', relation: '关联证据', ranking: '相关性排序', source: '来源证据' }[value] || value)
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
.advanced-tools { display:flex;flex-direction:column;gap:24px; }.advanced-tools section { display:flex;flex-direction:column;gap:14px;padding-bottom:22px;border-bottom:1px solid var(--yui-border); }.section-head,.button-row { display:flex;align-items:flex-start;justify-content:space-between;gap:12px; }.section-head h3 { margin:0;color:var(--yui-text);font-size:15px; }.section-head p,.status-text { margin:4px 0 0;color:var(--yui-muted);font-size:12px;line-height:1.5; }dl { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0; }dl div { padding:10px;background:var(--yui-surface-muted);border-radius:var(--yui-radius-control); }dt { color:var(--yui-muted);font-size:11px; }dd { margin:4px 0 0;color:var(--yui-text);font-weight:700; }.form-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px; }.form-grid>label { display:flex;flex-direction:column;gap:8px;color:var(--yui-muted);font-size:12px; }.form-grid :deep(.el-select){width:100%;}.relation-controls { display:flex; flex-wrap:wrap; align-items:center; gap:14px; }.relation-controls label { display:flex; align-items:center; gap:7px; color:var(--yui-muted); font-size:12px; }.relation-controls label:last-child { min-width:180px; flex:1; flex-direction:column; align-items:stretch; gap:3px; }.layer-picker,.switches,.button-row { display:flex;flex-wrap:wrap;gap:8px; }.layer-picker button { min-height:30px;border:1px solid var(--yui-border);border-radius:var(--yui-radius-control);background:var(--yui-surface);color:var(--yui-text);cursor:pointer; }.layer-picker button[aria-pressed="true"]{border-color:var(--yui-accent);background:var(--yui-accent-soft);}.trace { display:flex;flex-direction:column;gap:5px;padding:10px;border-radius:var(--yui-radius-card);background:var(--yui-surface-muted);color:var(--yui-muted);font-size:11px; }.trace strong{color:var(--yui-text);}.trace code{overflow-wrap:anywhere}.results,.candidates{display:grid;gap:8px}.results article{display:grid;grid-template-columns:24px 1fr;gap:8px;padding:10px;border-bottom:1px solid var(--yui-border)}.results p{margin:0;color:var(--yui-text);font-size:12px}.results span{color:var(--yui-muted);font-size:11px}.recall-explanation{display:flex;flex-direction:column;gap:2px;margin-top:7px;padding:7px 9px;border-left:2px solid var(--yui-accent);background:var(--yui-accent-soft);}.recall-explanation strong{color:var(--yui-text);font-size:11px}.recall-explanation small{color:var(--yui-muted);font-size:10px}.result-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:7px}.feedback-row{display:flex;flex-wrap:wrap;gap:4px}.score-components{display:grid;grid-template-columns:repeat(6,minmax(48px,1fr));gap:4px;margin-top:7px}.score-components span{display:flex;min-width:0;flex-direction:column;padding:5px;background:var(--yui-surface-muted);border-radius:var(--yui-radius-control)}.score-components small{font-size:9px}.score-components strong{color:var(--yui-text);font-size:10px}.candidates article{display:flex;justify-content:space-between;gap:12px;padding:8px;background:var(--yui-danger-soft);border-radius:var(--yui-radius-control);font-size:11px}.switches label{display:flex;align-items:center;gap:5px;color:var(--yui-text);font-size:12px}
.rebuild-progress{display:grid;gap:6px}.rebuild-progress span,.rebuild-error{font-size:12px}.rebuild-error{color:var(--yui-danger)}
@media(max-width:600px){.form-grid,dl{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}.score-components{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>

<template>
  <section class="review" aria-labelledby="memory-review-title">
    <div class="review-heading"><h3 id="memory-review-title">{{ t('memoryView.needsReview') }}</h3><el-tag :type="docs.length ? 'warning' : 'success'">{{ t('memoryView.countItems', { count: docs.length }) }}</el-tag></div>
    <AsyncState :loading="loading" :error="error" :empty="docs.length === 0" :empty-text="t('memoryView.reviewEmpty')" :loading-text="t('memoryView.reviewLoading')" @retry="emit('retry')">
      <template #empty>
        <p class="review-empty-hint">{{ t('memoryView.reviewEmptyHint') }}</p>
      </template>
      <div class="review-list">
        <article v-for="doc in docs" :key="doc.id">
          <div><strong>{{ doc.type || t('memoryView.memoryFallback') }}</strong><p>{{ compactText(doc.text, 140) }}</p></div>
          <div class="review-meta"><el-tag size="small" type="info">{{ layerLabel(doc.layer) }}</el-tag><span>{{ reviewReason(doc) }}</span><div class="review-actions"><el-button size="small" type="success" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'approve')">{{ t('memoryView.reviewApprove') }}</el-button><el-button size="small" type="danger" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'reject')">{{ t('memoryView.reviewReject') }}</el-button><el-button type="primary" link @click="emit('review', doc)">{{ t('memoryView.reviewDetails') }}</el-button></div></div>
        </article>
      </div>
    </AsyncState>
  </section>
</template>
<script setup lang="ts">
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import { ElButton, ElTag } from 'element-plus'
import { computed } from 'vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { t } from '@/i18n'
import type { MemoryDoc } from './memory-panel-types'
const props = defineProps<{ docs: MemoryDoc[]; compactText: (text?: string | null, limit?: number) => string; qualityPercent: (doc: MemoryDoc) => string; processingId: string; loading?: boolean; error?: string }>()
const emit = defineEmits<{ review: [doc: MemoryDoc]; decide: [payload: { doc: MemoryDoc; decision: 'approve' | 'reject' }]; retry: [] }>()
const decide = (doc: MemoryDoc, decision: 'approve' | 'reject') => {
  if (props.processingId) return
  emit('decide', { doc, decision })
}
const layerLabels = computed<Record<string, string>>(() => ({
  profile: t('memoryView.reviewLayerProfile'),
  working: t('memoryView.reviewLayerWorking'),
  episodic: t('memoryView.reviewLayerEpisodic'),
  relationship: t('memoryView.reviewLayerRelationship'),
  reflective: t('memoryView.reviewLayerReflective'),
  semantic: t('memoryView.reviewLayerSemantic'),
}))
const layerLabel = (value?: string) => layerLabels.value[String(value || '')] || t('memoryView.uncategorized')
const reviewReason = (doc: MemoryDoc) => {
  const metadata = doc.metadata || {}
  if (metadata.memory_role === 'tool_permission') return t('memoryView.reviewReasonPermission')
  if (metadata.sensitive_category && metadata.sensitive_category !== 'none') return t('memoryView.reviewReasonSensitive', { category: String(metadata.sensitive_category) })
  if (metadata.admission_reason === 'untrusted_source_requires_review') return t('memoryView.reviewReasonUntrusted')
  return t('memoryView.reviewReasonUnknown')
}
</script>
<style scoped>
.review,.review-list { display: flex; flex-direction: column; gap: 12px; }.review-empty-hint { max-width: 420px; margin: 0 auto; color: var(--yui-muted); font-size: 12px; line-height: 1.6; text-align: center; }
.review-heading,.review-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.review-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.review-heading p { margin: 4px 0 0; color: var(--yui-muted); font-size: 11px; line-height: 1.45; }.review-list article { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--yui-border); }.review-list strong { color: var(--yui-text); }.review-list p { margin: 5px 0 0; color: var(--yui-text); font-size: 13px; line-height: 1.55; }.review-meta { flex-wrap: wrap; justify-content: flex-end; color: var(--yui-muted); font-size: 12px; }.review-actions { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 760px) { .review-list article { flex-direction: column; }.review-meta { justify-content: flex-start; } }
</style>

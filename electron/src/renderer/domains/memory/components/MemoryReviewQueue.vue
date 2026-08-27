<template>
  <section class="review" aria-labelledby="memory-review-title">
    <div class="review-heading"><div><h3 id="memory-review-title">待确认记忆</h3><p>这些内容暂不参与召回，确认后才会进入可用记忆。</p></div><el-tag :type="docs.length ? 'warning' : 'success'">{{ docs.length }} 条</el-tag></div>
    <AsyncState :loading="loading" :error="error" :empty="docs.length === 0" empty-text="当前没有待确认的记忆" loading-text="正在读取待确认记忆…" @retry="emit('retry')">
      <div class="review-list">
        <article v-for="doc in docs" :key="doc.id">
          <div><strong>{{ doc.type || '记忆' }}</strong><p>{{ compactText(doc.text, 140) }}</p></div>
          <div class="review-meta"><el-tag size="small" type="info">{{ doc.layer || '未分类' }}</el-tag><span>质量 {{ qualityPercent(doc) }}</span><div class="review-actions"><el-button size="small" type="success" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'approve')">保留</el-button><el-button size="small" type="danger" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'reject')">拒绝</el-button><el-button type="primary" link @click="emit('review', doc)">查看详情</el-button></div></div>
        </article>
      </div>
    </AsyncState>
  </section>
</template>
<script setup lang="ts">
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import type { MemoryDoc } from './memory-panel-types'
const props = defineProps<{ docs: MemoryDoc[]; compactText: (text?: string | null, limit?: number) => string; qualityPercent: (doc: MemoryDoc) => string; processingId: string; loading?: boolean; error?: string }>()
const emit = defineEmits<{ review: [doc: MemoryDoc]; decide: [payload: { doc: MemoryDoc; decision: 'approve' | 'reject' }]; retry: [] }>()
const decide = (doc: MemoryDoc, decision: 'approve' | 'reject') => {
  if (props.processingId) return
  emit('decide', { doc, decision })
}
</script>
<style scoped>
.review,.review-list { display: flex; flex-direction: column; gap: 12px; }.review-heading,.review-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.review-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.review-heading p { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }.review-list article { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--yui-border); }.review-list strong { color: var(--yui-text); }.review-list p { margin: 5px 0 0; color: var(--yui-text); font-size: 13px; line-height: 1.55; }.review-meta { flex-wrap: wrap; justify-content: flex-end; color: var(--yui-muted); font-size: 12px; }.review-actions { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 760px) { .review-list article { flex-direction: column; }.review-meta { justify-content: flex-start; } }
</style>

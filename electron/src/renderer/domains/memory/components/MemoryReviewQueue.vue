<template>
  <section class="review" aria-labelledby="memory-review-title">
    <div class="review-heading"><h3 id="memory-review-title">需要检查</h3><el-tag :type="docs.length ? 'warning' : 'success'">{{ docs.length }} 条</el-tag></div>
    <AsyncState :loading="loading" :error="error" :empty="docs.length === 0" empty-text="目前没有需要你检查的记录" loading-text="正在读取需要检查的记录…" @retry="emit('retry')">
      <div class="review-list">
        <article v-for="doc in docs" :key="doc.id">
          <div><strong>{{ doc.type || '记忆' }}</strong><p>{{ compactText(doc.text, 140) }}</p></div>
          <div class="review-meta"><el-tag size="small" type="info">{{ layerLabel(doc.layer) }}</el-tag><span>{{ reviewReason(doc) }}</span><div class="review-actions"><el-button size="small" type="success" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'approve')">保留并使用</el-button><el-button size="small" type="danger" plain :loading="props.processingId === doc.id" :disabled="props.processingId !== ''" @click="decide(doc, 'reject')">拒绝使用</el-button><el-button type="primary" link @click="emit('review', doc)">查看详情</el-button></div></div>
        </article>
      </div>
    </AsyncState>
  </section>
</template>
<script setup lang="ts">
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import { ElButton, ElTag } from 'element-plus'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import type { MemoryDoc } from './memory-panel-types'
const props = defineProps<{ docs: MemoryDoc[]; compactText: (text?: string | null, limit?: number) => string; qualityPercent: (doc: MemoryDoc) => string; processingId: string; loading?: boolean; error?: string }>()
const emit = defineEmits<{ review: [doc: MemoryDoc]; decide: [payload: { doc: MemoryDoc; decision: 'approve' | 'reject' }]; retry: [] }>()
const decide = (doc: MemoryDoc, decision: 'approve' | 'reject') => {
  if (props.processingId) return
  emit('decide', { doc, decision })
}
const layerLabels: Record<string, string> = { profile: '偏好与称呼', working: '当前事项', episodic: '发生过的事', relationship: '相处方式', reflective: '经验总结', semantic: '稳定事实' }
const layerLabel = (value?: string) => layerLabels[String(value || '')] || '未分类'
const reviewReason = (doc: MemoryDoc) => {
  const metadata = doc.metadata || {}
  if (metadata.memory_role === 'tool_permission') return '涉及工具或权限，需要你决定'
  if (metadata.sensitive_category && metadata.sensitive_category !== 'none') return `包含敏感信息：${metadata.sensitive_category}`
  if (metadata.admission_reason === 'untrusted_source_requires_review') return '来源还没有被验证'
  return '来源需要检查'
}
</script>
<style scoped>
.review,.review-list { display: flex; flex-direction: column; gap: 12px; }.review-heading,.review-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.review-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.review-heading p { margin: 4px 0 0; color: var(--yui-muted); font-size: 11px; line-height: 1.45; }.review-list article { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--yui-border); }.review-list strong { color: var(--yui-text); }.review-list p { margin: 5px 0 0; color: var(--yui-text); font-size: 13px; line-height: 1.55; }.review-meta { flex-wrap: wrap; justify-content: flex-end; color: var(--yui-muted); font-size: 12px; }.review-actions { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 760px) { .review-list article { flex-direction: column; }.review-meta { justify-content: flex-start; } }
</style>

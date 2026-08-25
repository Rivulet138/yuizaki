<template>
  <section class="review" aria-labelledby="memory-review-title">
    <div class="review-heading"><div><h3 id="memory-review-title">待复核文档</h3><p>检查低置信度或低质量文档后再保留。</p></div><el-tag :type="docs.length ? 'warning' : 'success'">{{ docs.length }} 条</el-tag></div>
    <div v-if="docs.length" class="review-list">
      <article v-for="doc in docs" :key="doc.id">
        <div><strong>{{ doc.type || '记忆' }}</strong><p>{{ compactText(doc.text, 140) }}</p></div>
        <div class="review-meta"><el-tag size="small" type="info">{{ doc.layer || '未分类' }}</el-tag><span>质量 {{ qualityPercent(doc) }}</span><el-button type="primary" link @click="emit('review', doc)">打开复核</el-button></div>
      </article>
    </div>
    <el-empty v-else description="当前没有待确认的记忆" :image-size="64" />
  </section>
</template>
<script setup lang="ts">
import type { MemoryDoc } from './memory-panel-types'
defineProps<{ docs: MemoryDoc[]; compactText: (text?: string | null, limit?: number) => string; qualityPercent: (doc: MemoryDoc) => string }>()
const emit = defineEmits<{ review: [doc: MemoryDoc] }>()
</script>
<style scoped>
.review,.review-list { display: flex; flex-direction: column; gap: 12px; }.review-heading,.review-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.review-heading h3 { margin: 0; color: var(--yui-text); font-size: 15px; }.review-heading p { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }.review-list article { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--yui-border); }.review-list strong { color: var(--yui-text); }.review-list p { margin: 5px 0 0; color: var(--yui-text); font-size: 13px; line-height: 1.55; }.review-meta { flex-wrap: wrap; justify-content: flex-end; color: var(--yui-muted); font-size: 12px; }
@media (max-width: 760px) { .review-list article { flex-direction: column; }.review-meta { justify-content: flex-start; } }
</style>

<template>
  <section class="overview" aria-labelledby="memory-overview-title">
    <div class="overview-heading">
      <div>
        <h3 id="memory-overview-title">使用情况</h3>
      </div>
      <span v-if="loading" class="loading-label" role="status">正在刷新…</span>
    </div>

    <div v-if="error" class="overview-error" role="alert">
      <span>{{ error }}</span>
      <el-button link type="danger" size="small" @click="emit('retry')">重试概览</el-button>
    </div>

    <dl class="metric-grid" aria-label="记忆状态统计">
      <div><dt>已保存</dt><dd>{{ overview?.total ?? 0 }}</dd></div>
      <div><dt>可用于对话</dt><dd>{{ overview?.recallable ?? 0 }}</dd></div>
      <div><dt>需要检查</dt><dd>{{ reviewCount }}</dd></div>
      <div><dt>暂停使用</dt><dd>{{ forgottenCount }}</dd></div>
    </dl>

    <section class="overview-section" aria-labelledby="memory-layer-title">
        <div class="section-heading"><div><h4 id="memory-layer-title">按内容类别</h4></div></div>
      <div class="layer-list">
        <button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="selectedLayer === layer.value" @click="emit('select-layer', layer.value)">
          <strong>{{ layer.label }}</strong><span>{{ layer.desc }}</span><b>{{ layer.count ?? 0 }}</b>
        </button>
      </div>
    </section>

    <div class="overview-columns">
      <section class="overview-section" aria-labelledby="memory-activity-title">
        <div class="section-heading"><h4 id="memory-activity-title">最近活动</h4><span>{{ overview?.latest_activity.length ?? 0 }} 条</span></div>
        <ul v-if="overview?.latest_activity.length" class="activity-list">
          <li v-for="item in overview.latest_activity" :key="`${item.id}-${item.updated_at || item.action || ''}`">
            <div>
              <strong>{{ activityTitle(item) }}</strong>
              <span>{{ activitySummary(item) }}</span>
              <small>{{ activityMeta(item) }}</small>
            </div>
            <time v-if="item.updated_at" :datetime="item.updated_at">{{ formatTime(item.updated_at) }}</time>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无最近活动。</p>
      </section>

      <section class="overview-section" aria-labelledby="memory-forgotten-title">
        <div class="section-heading"><div><h4 id="memory-forgotten-title">暂停使用的记忆</h4></div><span>{{ forgottenDocs.length }} 条</span></div>
        <ul v-if="forgottenDocs.length" class="forgotten-list">
          <li v-for="doc in forgottenDocs" :key="doc.id">
            <div><strong>{{ compactText(doc.text) }}</strong><span>{{ layerLabel(doc.layer) }} · {{ docTypeLabel(doc.type) }}</span></div>
            <el-button
              :data-testid="`memory-restore-${doc.id}`" size="small" plain
              :loading="restoringDocIds.has(doc.id)" :disabled="restoringDocIds.has(doc.id)"
              @click="emit('restore', doc.id)"
            >重新启用</el-button>
          </li>
        </ul>
        <p v-else class="empty-copy">目前没有暂停使用的记忆。</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElButton } from 'element-plus'
import type { MemoryOverview } from '@/api/clients/memory-client'
import type { MemoryDoc, MemoryLayer } from './memory-panel-types'

import 'element-plus/es/components/button/style/css'

const props = defineProps<{
  overview: MemoryOverview | null
  forgottenDocs: MemoryDoc[]
  layers: MemoryLayer[]
  selectedLayer: string
  loading: boolean
  error?: string
  restoringDocIds: Set<string>
}>()

const emit = defineEmits<{ 'select-layer': [value: string]; restore: [id: string]; retry: [] }>()
const reviewCount = computed(() => Number(props.overview?.by_review_status.pending ?? 0) + Number(props.overview?.by_review_status.unreviewed ?? 0))
const forgottenCount = computed(() => props.overview?.by_state.forgotten ?? props.forgottenDocs.length)
const compactText = (value: string, limit = 86) => value.length > limit ? `${value.slice(0, limit - 1)}…` : value
const formatTime = (value: string) => value.replace('T', ' ').slice(0, 16)
const layerLabel = (value?: string) => props.layers.find(layer => layer.value === value)?.label || '未分类'
const docTypeLabels: Record<string, string> = { fact: '事实', preference: '偏好', event: '事件', promise: '约定', taboo: '边界', summary: '总结', chat: '对话记录' }
const docTypeLabel = (value?: string) => docTypeLabels[String(value || '')] || value || '记忆'
type ActivityItem = MemoryOverview['latest_activity'][number]
const eventKindLabels: Record<string, string> = {
  care_signal: '记录了你的近况',
  mood_shift: '更新了最近状态',
  trust_shift: '更新了相处状态',
  gratitude: '记住了你的感谢',
  preference_confirmed: '记住了一个偏好',
  task_completed: '记录了一项已完成事项',
}
const moodLabels: Record<string, string> = { tired: '有些疲惫', happy: '心情不错', sad: '有些低落', anxious: '有些焦虑', calm: '比较平静', busy: '比较忙' }
const readableText = (value: string) => value
  .replace(/\b(?:kind|mood|affinity|energy|confidence|source|layer|memory_role)\s*=\s*[^,;\s]+/gi, '')
  .replace(/\s{2,}/g, ' ')
  .replace(/[：:]\s*$/, '')
  .trim()
const activityTitle = (item: ActivityItem) => {
  const eventKind = String(item.relationship_event?.kind || '')
  if (eventKindLabels[eventKind]) return eventKindLabels[eventKind]
  if (item.memory_role === 'user_fact') return '记住了一个关于你的事实'
  if (item.memory_role === 'tool_permission') return '有一项权限记录需要检查'
  if (item.action === 'soft_forget' || item.state === 'forgotten') return '暂停使用了一条记忆'
  if (item.action === 'restore') return '重新启用了一条记忆'
  if (item.action === 'corrected') return '修正了一条记忆'
  return '更新了一条记忆'
}
const activitySummary = (item: ActivityItem) => {
  const mood = moodLabels[String(item.relationship_event?.mood || '')]
  if (mood) return `最近状态：${mood}`
  const text = readableText(item.text)
  return text || '内容未提供'
}
const activityMeta = (item: ActivityItem) => {
  if (item.memory_role === 'tool_permission' || item.review_status === 'pending') return '需要检查'
  if (item.scope === 'session') return '本次会话'
  if (item.scope === 'global') return '所有工作区'
  return '当前工作区'
}
</script>

<style scoped>
.overview,.overview-section { display: flex; min-width: 0; flex-direction: column; gap: 14px; }
.overview { gap: 20px; }
.overview-heading,.section-heading,.activity-list li,.forgotten-list li { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.overview-error { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border: 1px solid rgba(239,68,68,.28); border-radius: var(--yui-radius-card); background: var(--yui-danger-soft); color: #991b1b; font-size: 12px; }
h3,h4 { margin: 0; color: var(--yui-text); }
h3 { font-size: 15px; } h4 { font-size: 13px; }
.overview-heading p,.section-heading p { margin: 4px 0 0; color: var(--yui-muted); font-size: 11px; line-height: 1.45; }
.section-heading span,.loading-label,.empty-copy { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); margin: 0; border-block: 1px solid var(--yui-border); }
.metric-grid div { min-width: 0; padding: 14px; border-right: 1px solid var(--yui-border); }
.metric-grid div:last-child { border-right: 0; }
.metric-grid dt,.metric-grid small { color: var(--yui-muted); font-size: 11px; }
.metric-grid dd { margin: 4px 0; color: var(--yui-text); font-size: 23px; font-weight: 700; }
.metric-grid small { display: block; line-height: 1.4; }
.layer-list { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
.layer-list button { display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; min-height: 56px; padding: 10px 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface); color: var(--yui-text); text-align: left; cursor: pointer; }
.layer-list button[aria-pressed="true"] { border-color: var(--yui-accent); background: var(--yui-accent-soft); }
.layer-list span,.activity-list span,.activity-list small,.forgotten-list span { color: var(--yui-muted); font-size: 11px; }
.layer-list b { grid-row: 1/3; grid-column: 2; align-self: center; }
.overview-columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 24px; }
.activity-list,.forgotten-list { display: flex; max-height: 330px; flex-direction: column; gap: 0; margin: 0; padding: 0; overflow-y: auto; list-style: none; border-top: 1px solid var(--yui-border); }
.activity-list li,.forgotten-list li { padding: 11px 2px; border-bottom: 1px solid var(--yui-border); }
.activity-list li>div,.forgotten-list li>div { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.activity-list strong,.forgotten-list strong { overflow-wrap: anywhere; color: var(--yui-text); font-size: 12px; font-weight: 600; }
.activity-list time { flex: 0 0 auto; color: var(--yui-muted); font-size: 10px; }
.forgotten-list :deep(.el-button) { flex: 0 0 auto; }
@media(max-width:900px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.metric-grid div:nth-child(2){border-right:0}.metric-grid div:nth-child(-n+2){border-bottom:1px solid var(--yui-border)}.layer-list{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-columns{grid-template-columns:1fr}}
@media(max-width:560px){.metric-grid,.layer-list{grid-template-columns:1fr}.metric-grid div{border-right:0;border-bottom:1px solid var(--yui-border)}.metric-grid div:last-child{border-bottom:0}.activity-list li{flex-direction:column}.forgotten-list li{align-items:center}}
</style>

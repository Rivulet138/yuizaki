<template>
  <section class="overview" aria-labelledby="memory-overview-title">
    <div class="overview-heading">
      <div>
        <h3 id="memory-overview-title">记忆概览</h3>
        <p>统计当前范围内的文档数量、状态和最近变更。</p>
      </div>
      <span v-if="loading" class="loading-label" role="status">正在刷新…</span>
    </div>

    <div v-if="error" class="overview-error" role="alert">
      <span>{{ error }}</span>
      <el-button link type="danger" size="small" @click="emit('retry')">重试概览</el-button>
    </div>

    <dl class="metric-grid" aria-label="记忆状态统计">
      <div><dt>全部记忆</dt><dd>{{ overview?.total ?? 0 }}</dd><small>含不可召回文档</small></div>
      <div><dt>可召回</dt><dd>{{ overview?.recallable ?? 0 }}</dd><small>可用于检索</small></div>
      <div><dt>待复核</dt><dd>{{ reviewCount }}</dd><small>需要人工确认</small></div>
      <div><dt>已停止召回</dt><dd>{{ forgottenCount }}</dd><small>可恢复的记录</small></div>
    </dl>

    <section class="overview-section" aria-labelledby="memory-layer-title">
        <div class="section-heading"><h4 id="memory-layer-title">按层级统计</h4><span>点击层级查看文档</span></div>
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
            <div><strong>{{ compactText(item.text) }}</strong><span>{{ activityLabel(item.action, item.state) }} · {{ item.layer || '未分层' }}</span></div>
            <time v-if="item.updated_at" :datetime="item.updated_at">{{ formatTime(item.updated_at) }}</time>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无最近活动。</p>
      </section>

      <section class="overview-section" aria-labelledby="memory-forgotten-title">
        <div class="section-heading"><h4 id="memory-forgotten-title">已停止召回</h4><span>{{ forgottenDocs.length }} 条</span></div>
        <ul v-if="forgottenDocs.length" class="forgotten-list">
          <li v-for="doc in forgottenDocs" :key="doc.id">
            <div><strong>{{ compactText(doc.text) }}</strong><span>{{ doc.layer || '未分层' }} · {{ doc.type || '记忆' }}</span></div>
            <el-button
              :data-testid="`memory-restore-${doc.id}`" size="small" plain
              :loading="restoringDocIds.has(doc.id)" :disabled="restoringDocIds.has(doc.id)"
              @click="emit('restore', doc.id)"
            >恢复召回</el-button>
          </li>
        </ul>
        <p v-else class="empty-copy">没有已停止召回的记忆。</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MemoryOverview } from '@/api/clients/memory-client'
import type { MemoryDoc, MemoryLayer } from './memory-panel-types'

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
const activityLabel = (action?: string, state?: string) => ({
  soft_forget: '停止召回', restore: '恢复召回', corrected: '已修正', updated: '已更新', created: '已创建',
}[String(action || '')] || ({ forgotten: '停止召回', active: '当前有效', expired: '已过期', superseded: '已被替代' }[String(state || '')] || String(action || state || '已更新')))
</script>

<style scoped>
.overview,.overview-section { display: flex; min-width: 0; flex-direction: column; gap: 14px; }
.overview { gap: 20px; }
.overview-heading,.section-heading,.activity-list li,.forgotten-list li { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.overview-error { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border: 1px solid rgba(239,68,68,.28); border-radius: var(--yui-radius-card); background: var(--yui-danger-soft); color: #991b1b; font-size: 12px; }
h3,h4 { margin: 0; color: var(--yui-text); }
h3 { font-size: 15px; } h4 { font-size: 13px; }
.overview-heading p,.section-heading span,.loading-label,.empty-copy { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); margin: 0; border-block: 1px solid var(--yui-border); }
.metric-grid div { min-width: 0; padding: 14px; border-right: 1px solid var(--yui-border); }
.metric-grid div:last-child { border-right: 0; }
.metric-grid dt,.metric-grid small { color: var(--yui-muted); font-size: 11px; }
.metric-grid dd { margin: 4px 0; color: var(--yui-text); font-size: 23px; font-weight: 700; }
.metric-grid small { display: block; line-height: 1.4; }
.layer-list { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
.layer-list button { display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; min-height: 56px; padding: 10px 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface); color: var(--yui-text); text-align: left; cursor: pointer; }
.layer-list button[aria-pressed="true"] { border-color: var(--yui-accent); background: var(--yui-accent-soft); }
.layer-list span,.activity-list span,.forgotten-list span { color: var(--yui-muted); font-size: 11px; }
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

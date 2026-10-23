<template>
  <section class="overview" aria-labelledby="memory-overview-title">
    <div class="overview-heading">
      <div>
        <h3 id="memory-overview-title">{{ t('memoryView.overviewTitle') }}</h3>
      </div>
      <span v-if="loading" class="loading-label" role="status">{{ t('memoryView.overviewLoading') }}</span>
    </div>

    <div v-if="error" class="overview-error" role="alert">
      <span>{{ error }}</span>
      <el-button link type="danger" size="small" @click="emit('retry')">{{ t('memoryView.overviewRetry') }}</el-button>
    </div>

    <dl class="metric-grid" :aria-label="t('memoryView.metricsAria')">
      <div><dt>{{ t('memoryView.saved') }}</dt><dd>{{ overview?.total ?? 0 }}</dd></div>
      <div><dt>{{ t('memoryView.availableForChat') }}</dt><dd>{{ overview?.recallable ?? 0 }}</dd></div>
      <div><dt>{{ t('memoryView.needsReview') }}</dt><dd>{{ reviewCount }}</dd></div>
      <div><dt>{{ t('memoryView.paused') }}</dt><dd>{{ forgottenCount }}</dd></div>
    </dl>

    <details class="overview-section overview-disclosure" open aria-labelledby="memory-layer-title">
      <summary class="section-heading"><h4 id="memory-layer-title">{{ t('memoryView.layersTitle') }}</h4><span>{{ t('memoryView.layersHint') }}</span></summary>
      <div class="layer-list">
        <button v-for="layer in layers" :key="layer.value" type="button" :aria-pressed="selectedLayer === layer.value" @click="emit('select-layer', layer.value)">
          <strong>{{ layer.label }}</strong><span>{{ layer.desc }}</span><b>{{ layer.count ?? 0 }}</b>
        </button>
      </div>
    </details>

    <div class="overview-columns">
      <details class="overview-section overview-disclosure" open aria-labelledby="memory-activity-title">
        <summary class="section-heading"><h4 id="memory-activity-title">{{ t('memoryView.recentActivity') }}</h4><span>{{ t('memoryView.countItems', { count: overview?.latest_activity.length ?? 0 }) }}</span></summary>
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
        <p v-else class="empty-copy">{{ t('memoryView.activityEmpty') }}</p>
      </details>

      <details class="overview-section overview-disclosure" aria-labelledby="memory-forgotten-title">
        <summary class="section-heading"><h4 id="memory-forgotten-title">{{ t('memoryView.pausedMemories') }}</h4><span>{{ t('memoryView.countItems', { count: forgottenDocs.length }) }}</span></summary>
        <ul v-if="forgottenDocs.length" class="forgotten-list">
          <li v-for="doc in forgottenDocs" :key="doc.id">
            <div><strong>{{ compactText(doc.text) }}</strong><span>{{ layerLabel(doc.layer) }} · {{ docTypeLabel(doc.type) }}</span></div>
            <el-button
              :data-testid="`memory-restore-${doc.id}`" size="small" plain
              :loading="restoringDocIds.has(doc.id)" :disabled="restoringDocIds.has(doc.id)"
              @click="emit('restore', doc.id)"
            >{{ t('memoryView.restore') }}</el-button>
          </li>
        </ul>
        <p v-else class="empty-copy">{{ t('memoryView.pausedEmpty') }}</p>
      </details>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElButton } from 'element-plus'
import type { MemoryOverview } from '@/api/clients/memory-client'
import { t } from '@/i18n'
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
const layerLabel = (value?: string) => props.layers.find(layer => layer.value === value)?.label || t('memoryView.uncategorized')
const docTypeLabels = computed<Record<string, string>>(() => ({
  fact: t('memoryView.docTypeFact'),
  preference: t('memoryView.docTypePreference'),
  event: t('memoryView.docTypeEvent'),
  promise: t('memoryView.docTypePromise'),
  taboo: t('memoryView.docTypeTaboo'),
  summary: t('memoryView.docTypeSummary'),
  chat: t('memoryView.docTypeChat'),
}))
const docTypeLabel = (value?: string) => docTypeLabels.value[String(value || '')] || value || t('memoryView.memoryFallback')
type ActivityItem = MemoryOverview['latest_activity'][number]
const eventKindLabels = computed<Record<string, string>>(() => ({
  care_signal: t('memoryView.eventCareSignal'),
  mood_shift: t('memoryView.eventMoodShift'),
  trust_shift: t('memoryView.eventTrustShift'),
  gratitude: t('memoryView.eventGratitude'),
  preference_confirmed: t('memoryView.eventPreferenceConfirmed'),
  task_completed: t('memoryView.eventTaskCompleted'),
}))
const moodLabels = computed<Record<string, string>>(() => ({
  tired: t('memoryView.moodTired'),
  happy: t('memoryView.moodHappy'),
  sad: t('memoryView.moodSad'),
  anxious: t('memoryView.moodAnxious'),
  calm: t('memoryView.moodCalm'),
  busy: t('memoryView.moodBusy'),
}))
const readableText = (value: string) => value
  .replace(/\b(?:kind|mood|affinity|energy|confidence|source|layer|memory_role)\s*=\s*[^,;\s]+/gi, '')
  .replace(/\s{2,}/g, ' ')
  .replace(/[：:]\s*$/, '')
  .trim()
const activityTitle = (item: ActivityItem) => {
  const eventKind = String(item.relationship_event?.kind || '')
  if (eventKindLabels.value[eventKind]) return eventKindLabels.value[eventKind]
  if (item.memory_role === 'user_fact') return t('memoryView.activityUserFact')
  if (item.memory_role === 'tool_permission') return t('memoryView.activityToolPermission')
  if (item.action === 'soft_forget' || item.state === 'forgotten') return t('memoryView.activitySoftForget')
  if (item.action === 'restore') return t('memoryView.activityRestore')
  if (item.action === 'corrected') return t('memoryView.activityCorrected')
  return t('memoryView.activityUpdated')
}
const activitySummary = (item: ActivityItem) => {
  const mood = moodLabels.value[String(item.relationship_event?.mood || '')]
  if (mood) return t('memoryView.activityMood', { mood })
  const text = readableText(item.text)
  return text || t('memoryView.activityNoContent')
}
const activityMeta = (item: ActivityItem) => {
  if (item.memory_role === 'tool_permission' || item.review_status === 'pending') return t('memoryView.needsReview')
  if (item.scope === 'session') return t('memoryView.scopeSession')
  if (item.scope === 'global') return t('memoryView.scopeAllWorkspaces')
  return t('memoryView.scopeWorkspace')
}
</script>

<style scoped>
.overview,.overview-section { display: flex; min-width: 0; flex-direction: column; gap: 14px; }
.overview { gap: 20px; }
.overview-disclosure { padding: 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-muted); }
.overview-disclosure > summary { cursor: pointer; list-style: none; }
.overview-disclosure > summary::-webkit-details-marker { display: none; }
.overview-disclosure > summary::after { content: '＋'; color: var(--yui-muted); font-size: 14px; }
.overview-disclosure[open] > summary::after { content: '−'; }
.overview-disclosure > .layer-list,.overview-disclosure > .activity-list,.overview-disclosure > .forgotten-list { margin-top: 2px; }
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

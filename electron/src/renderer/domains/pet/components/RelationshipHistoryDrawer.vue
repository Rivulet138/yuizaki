<template>
  <el-drawer
    :model-value="modelValue"
    title="关系历史"
    size="min(640px, 94vw)"
    append-to-body
    @update:model-value="$emit('update:modelValue', Boolean($event))"
    @open="load"
  >
    <div class="relationship-history">
      <div class="history-toolbar">
        <el-segmented v-model="mode" :options="modeOptions" size="small" />
        <div class="history-actions">
          <el-tag size="small" type="info">{{ companionName }}</el-tag>
          <el-button :icon="Refresh" plain size="small" :loading="loading" @click="load">刷新</el-button>
        </div>
      </div>

      <AsyncState
        :loading="loading"
        :error="error"
        :empty="Boolean(payload) && visibleEvents.length === 0"
        loading-text="加载关系历史"
        empty-text="暂无关系事件"
        :show-retry="false"
      >
        <template v-if="payload">
          <dl class="relationship-summary" aria-label="关系摘要">
            <div><dt>相处阶段</dt><dd>{{ relationshipStageLabel(payload.summary.relationship_stage) }}</dd></div>
            <div><dt>最近趋势</dt><dd>{{ relationshipTrendLabel(payload.summary.relationship_trend) }}</dd></div>
            <div><dt>事件</dt><dd>{{ payload.summary.event_count }}</dd></div>
            <div><dt>里程碑</dt><dd>{{ payload.summary.milestone_count }}</dd></div>
            <div><dt>互动节奏</dt><dd>{{ proactiveBudgetLabel(payload.summary.proactive_budget) }}</dd></div>
          </dl>

          <ol v-if="visibleEvents.length" class="history-list">
            <li v-for="(event, index) in visibleEvents" :key="eventKey(event, index)" class="history-row">
              <div class="history-row__head">
                <strong>{{ relationshipEventLabel(event.kind) }}</strong>
                <time>{{ formatTime(event.timestamp) }}</time>
              </div>
              <p v-if="event.text">{{ event.text }}</p>
              <dl class="history-row__meta">
                <div v-if="event.mood"><dt>最近状态</dt><dd>{{ moodLabel(event.mood) }}</dd></div>
                <div v-if="isNumber(event.affinity)"><dt>亲近度</dt><dd>{{ formatRatio(event.affinity) }}</dd></div>
                <div v-if="isNumber(event.energy)"><dt>精力</dt><dd>{{ formatRatio(event.energy) }}</dd></div>
                <div v-if="isNumber(event.importance)"><dt>重要度</dt><dd>{{ formatRatio(event.importance) }}</dd></div>
                <div><dt>保存范围</dt><dd>{{ scopeLabel(event.scope) }}</dd></div>
                <div v-if="event.milestone"><dt>类型</dt><dd>里程碑</dd></div>
              </dl>
            </li>
          </ol>
        </template>
      </AsyncState>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSegmented } from 'element-plus'
import 'element-plus/es/components/segmented/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed, ref, watch } from 'vue'
import { getActivePinia } from 'pinia'
import { ElDrawer } from 'element-plus'
import 'element-plus/es/components/drawer/style/css'
import { Refresh } from '@element-plus/icons-vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import {
  companionClient,
  type RelationshipHistoryEvent,
  type RelationshipHistoryPayload,
} from '@/api/clients/companion-client'
import { useCompanionStore } from '@/stores/companionStore'

const props = defineProps<{ modelValue: boolean }>()
defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const pinia = getActivePinia()
const companionStore = pinia ? useCompanionStore(pinia) : null
const activeCompanionId = computed(() => companionStore?.activeCompanionId ?? 'default')
const activeCompanion = computed(() => companionStore?.activeCompanion ?? null)
const payload = ref<RelationshipHistoryPayload | null>(null)
const loading = ref(false)
const error = ref('')
const mode = ref<'all' | 'milestones'>('all')
const modeOptions = [
  { label: '全部', value: 'all' },
  { label: '里程碑', value: 'milestones' },
]
let requestId = 0

const companionName = computed(() => activeCompanion.value?.name || activeCompanionId.value)
const visibleEvents = computed(() => mode.value === 'milestones'
  ? (payload.value?.events ?? []).filter((event) => event.milestone)
  : payload.value?.events ?? [])

const load = async () => {
  if (!props.modelValue || loading.value) return
  const currentRequest = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await companionClient.relationshipHistory(activeCompanionId.value, 100)
    if (currentRequest === requestId) payload.value = result
  } catch (loadError) {
    if (currentRequest === requestId) {
      payload.value = null
      error.value = loadError instanceof Error ? loadError.message : '关系历史加载失败'
    }
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const formatRatio = (value: number | undefined) => isNumber(value) ? `${Math.round(value * 100)}%` : '未设置'
const relationshipEventLabels: Record<string, string> = {
  care_signal: '记录了你的近况',
  mood_shift: '更新了最近状态',
  trust_shift: '更新了相处状态',
  gratitude: '记住了你的感谢',
  preference_confirmed: '记住了一个偏好',
  task_completed: '记录了一项已完成事项',
  state_snapshot: '记录了当前状态',
}
const relationshipStageLabels: Record<string, string> = {
  warming: '正在熟悉',
  stable: '相处稳定',
  close: '关系亲近',
}
const relationshipTrendLabels: Record<string, string> = {
  rising: '逐渐靠近',
  steady: '保持稳定',
  falling: '需要留意',
}
const moodLabels: Record<string, string> = {
  tired: '有些疲惫',
  happy: '心情不错',
  sad: '有些低落',
  anxious: '有些焦虑',
  calm: '比较平静',
  busy: '比较忙',
}
const scopeLabels: Record<string, string> = { global: '所有工作区', workspace: '当前工作区', session: '当前会话' }
const relationshipEventLabel = (value?: string | null) => relationshipEventLabels[String(value || '')] || '更新了相处状态'
const relationshipStageLabel = (value?: string | null) => relationshipStageLabels[String(value || '')] || '未设置'
const relationshipTrendLabel = (value?: string | null) => relationshipTrendLabels[String(value || '')] || '未设置'
const moodLabel = (value?: string | null) => moodLabels[String(value || '')] || value || '未设置'
const scopeLabel = (value?: string | null) => scopeLabels[String(value || '')] || '当前工作区'
const proactiveBudgetLabel = (value?: number | null) => {
  if (!isNumber(value)) return '未设置'
  if (value < 0.85) return '较克制'
  if (value >= 1.2) return '较主动'
  return '适中'
}
const formatTime = (value: string | null | undefined) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(date)
}
const eventKey = (event: RelationshipHistoryEvent, index: number) =>
  `${event.timestamp || 'unknown'}:${event.kind || 'event'}:${index}`

watch(() => [props.modelValue, activeCompanionId.value] as const, ([visible]) => {
  if (visible) void load()
  else requestId += 1
}, { immediate: true })
</script>

<style scoped>
.relationship-history { display: grid; min-width: 0; gap: 16px; }
.history-toolbar, .history-actions, .history-row__head { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 10px; }
.history-actions { justify-content: flex-end; flex-wrap: wrap; }
.relationship-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 0; border-block: 1px solid var(--yui-border); }
.relationship-summary > div { display: grid; gap: 4px; min-width: 0; padding: 12px 8px; text-align: center; }
dt { color: var(--yui-muted); font-size: 12px; }
dd { min-width: 0; margin: 0; color: var(--yui-text); font-size: 13px; overflow-wrap: anywhere; }
.relationship-summary dd { font-weight: 700; }
.history-list { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.history-row { display: grid; gap: 9px; padding: 14px 2px; border-bottom: 1px solid var(--yui-border); }
.history-row__head strong { color: var(--yui-text); font-size: 13px; }
.history-row__head time { color: var(--yui-muted); font-size: 12px; white-space: nowrap; }
.history-row p { margin: 0; color: var(--yui-text); font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
.history-row__meta { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0; }
.history-row__meta div { display: inline-flex; align-items: baseline; gap: 5px; }
.history-row__meta dd { font-size: 12px; }
@media (max-width: 760px) {
  .history-toolbar { align-items: flex-start; flex-direction: column; }
  .history-actions { width: 100%; justify-content: space-between; }
  .relationship-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .relationship-summary > div:last-child { grid-column: 1 / -1; }
}
</style>

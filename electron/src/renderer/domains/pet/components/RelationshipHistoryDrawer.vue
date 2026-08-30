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
            <div><dt>阶段</dt><dd>{{ payload.summary.relationship_stage || '未设置' }}</dd></div>
            <div><dt>趋势</dt><dd>{{ payload.summary.relationship_trend || '未设置' }}</dd></div>
            <div><dt>事件</dt><dd>{{ payload.summary.event_count }}</dd></div>
            <div><dt>里程碑</dt><dd>{{ payload.summary.milestone_count }}</dd></div>
            <div><dt>主动预算</dt><dd>{{ payload.summary.proactive_budget }}</dd></div>
          </dl>

          <ol v-if="visibleEvents.length" class="history-list">
            <li v-for="(event, index) in visibleEvents" :key="eventKey(event, index)" class="history-row">
              <div class="history-row__head">
                <strong>{{ event.kind || 'event' }}</strong>
                <time>{{ formatTime(event.timestamp) }}</time>
              </div>
              <p v-if="event.text">{{ event.text }}</p>
              <dl class="history-row__meta">
                <div v-if="event.mood"><dt>心情</dt><dd>{{ event.mood }}</dd></div>
                <div v-if="isNumber(event.affinity)"><dt>亲近度</dt><dd>{{ formatRatio(event.affinity) }}</dd></div>
                <div v-if="isNumber(event.energy)"><dt>精力</dt><dd>{{ formatRatio(event.energy) }}</dd></div>
                <div v-if="isNumber(event.importance)"><dt>重要度</dt><dd>{{ formatRatio(event.importance) }}</dd></div>
                <div><dt>范围</dt><dd>{{ event.scope || 'workspace' }}</dd></div>
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
import { computed, ref, watch } from 'vue'
import { getActivePinia } from 'pinia'
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

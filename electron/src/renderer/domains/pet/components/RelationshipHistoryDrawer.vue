<template>
  <el-drawer
    :model-value="modelValue"
    :title="t('petPanel.history.title')"
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
          <el-button :icon="Refresh" plain size="small" :loading="loading" @click="load">{{ t('petPanel.history.refresh') }}</el-button>
        </div>
      </div>

      <AsyncState
        :loading="loading"
        :error="error"
        :empty="Boolean(payload) && visibleEvents.length === 0"
        :loading-text="t('petPanel.history.loading')"
        :empty-text="t('petPanel.history.empty')"
        :show-retry="false"
      >
        <template v-if="payload">
          <dl class="relationship-summary" :aria-label="t('petPanel.history.summaryAria')">
            <div><dt>{{ t('petPanel.history.summaryStage') }}</dt><dd>{{ relationshipStageLabel(payload.summary.relationship_stage) }}</dd></div>
            <div><dt>{{ t('petPanel.history.summaryTrend') }}</dt><dd>{{ relationshipTrendLabel(payload.summary.relationship_trend) }}</dd></div>
            <div><dt>{{ t('petPanel.history.summaryEventCount') }}</dt><dd>{{ payload.summary.event_count }}</dd></div>
            <div><dt>{{ t('petPanel.history.summaryMilestoneCount') }}</dt><dd>{{ payload.summary.milestone_count }}</dd></div>
            <div><dt>{{ t('petPanel.history.summaryProactivity') }}</dt><dd>{{ proactiveBudgetLabel(payload.summary.proactive_budget) }}</dd></div>
          </dl>

          <ol v-if="visibleEvents.length" class="history-list">
            <li v-for="(event, index) in visibleEvents" :key="eventKey(event, index)" class="history-row">
              <div class="history-row__head">
                <strong>{{ relationshipEventLabel(event.kind) }}</strong>
                <time>{{ formatTime(event.timestamp) }}</time>
              </div>
              <p v-if="event.text">{{ event.text }}</p>
              <dl class="history-row__meta">
                <div v-if="event.mood"><dt>{{ t('petPanel.history.eventMood') }}</dt><dd>{{ moodLabel(event.mood) }}</dd></div>
                <div v-if="isNumber(event.affinity)"><dt>{{ t('petPanel.history.eventAffinity') }}</dt><dd>{{ formatRatio(event.affinity) }}</dd></div>
                <div v-if="isNumber(event.energy)"><dt>{{ t('petPanel.history.eventEnergy') }}</dt><dd>{{ formatRatio(event.energy) }}</dd></div>
                <div v-if="isNumber(event.importance)"><dt>{{ t('petPanel.history.eventImportance') }}</dt><dd>{{ formatRatio(event.importance) }}</dd></div>
                <div><dt>{{ t('petPanel.history.eventScope') }}</dt><dd>{{ scopeLabel(event.scope) }}</dd></div>
                <div v-if="event.milestone"><dt>{{ t('petPanel.history.eventType') }}</dt><dd>{{ t('petPanel.history.milestoneValue') }}</dd></div>
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
import { t } from '@/i18n'
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
const modeOptions = computed(() => [
  { label: t('petPanel.history.modeAll'), value: 'all' },
  { label: t('petPanel.history.modeMilestones'), value: 'milestones' },
])
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
      error.value = loadError instanceof Error
        ? loadError.message
        : t('petPanel.history.loadFailed')
    }
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const formatRatio = (value: number | undefined) => isNumber(value)
  ? `${Math.round(value * 100)}%`
  : t('petPanel.history.notSet')
const relationshipEventLabels = computed<Record<string, string>>(() => ({
  care_signal: t('petPanel.history.event.careSignal'),
  mood_shift: t('petPanel.history.event.moodShift'),
  trust_shift: t('petPanel.history.event.trustShift'),
  gratitude: t('petPanel.history.event.gratitude'),
  preference_confirmed: t('petPanel.history.event.preferenceConfirmed'),
  task_completed: t('petPanel.history.event.taskCompleted'),
  state_snapshot: t('petPanel.history.event.stateSnapshot'),
}))
const relationshipStageLabels = computed<Record<string, string>>(() => ({
  warming: t('petPanel.history.stage.warming'),
  stable: t('petPanel.history.stage.stable'),
  close: t('petPanel.history.stage.close'),
}))
const relationshipTrendLabels = computed<Record<string, string>>(() => ({
  rising: t('petPanel.history.trend.rising'),
  steady: t('petPanel.history.trend.steady'),
  falling: t('petPanel.history.trend.falling'),
}))
const moodLabels = computed<Record<string, string>>(() => ({
  tired: t('petPanel.history.mood.tired'),
  happy: t('petPanel.history.mood.happy'),
  sad: t('petPanel.history.mood.sad'),
  anxious: t('petPanel.history.mood.anxious'),
  calm: t('petPanel.history.mood.calm'),
  busy: t('petPanel.history.mood.busy'),
}))
const scopeLabels = computed<Record<string, string>>(() => ({
  global: t('petPanel.history.scope.global'),
  workspace: t('petPanel.history.scope.workspace'),
  session: t('petPanel.history.scope.session'),
}))
const relationshipEventLabel = (value?: string | null) =>
  relationshipEventLabels.value[String(value || '')] || t('petPanel.history.eventFallback')
const relationshipStageLabel = (value?: string | null) =>
  relationshipStageLabels.value[String(value || '')] || t('petPanel.history.notSet')
const relationshipTrendLabel = (value?: string | null) =>
  relationshipTrendLabels.value[String(value || '')] || t('petPanel.history.notSet')
const moodLabel = (value?: string | null) =>
  moodLabels.value[String(value || '')] || value || t('petPanel.history.notSet')
const scopeLabel = (value?: string | null) =>
  scopeLabels.value[String(value || '')] || t('petPanel.history.scopeFallback')
const proactiveBudgetLabel = (value?: number | null) => {
  if (!isNumber(value)) return t('petPanel.history.notSet')
  if (value < 0.85) return t('petPanel.history.proactivity.restrained')
  if (value >= 1.2) return t('petPanel.history.proactivity.active')
  return t('petPanel.history.proactivity.balanced')
}
const formatTime = (value: string | null | undefined) => {
  if (!value) return t('petPanel.history.unknownTime')
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

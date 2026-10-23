<template>
  <PanelShell :title="t('memoryView.personaTitle')" tone="admin">
    <div class="persona-panel">
      <div class="panel-toolbar">
        <div>
          <h3>{{ t('memoryView.personaCurrentState') }}</h3>
        </div>
        <el-button type="primary" plain :loading="loading" :disabled="loading" @click="loadHeartbeat">{{ t('memoryView.personaRefresh') }}</el-button>
      </div>

      <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="false" />

      <el-card shadow="never">
         <template #header>{{ t('memoryView.personaPetStatus') }}</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item :label="t('memoryView.personaMood')">{{ heartbeat?.persona?.mood || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('memoryView.personaEnergy')">{{ heartbeat?.persona?.energy || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('memoryView.personaAffinity')">{{ formatAffinity(heartbeat?.persona?.affinity) }}</el-descriptions-item>
          <el-descriptions-item :label="t('memoryView.personaRunningState')">{{ heartbeat?.running ? t('memoryView.personaRunning') : t('memoryView.personaStopped') }}</el-descriptions-item>
          <el-descriptions-item :label="t('memoryView.personaTickCount')">{{ heartbeat?.tick_count || 0 }}</el-descriptions-item>
          <el-descriptions-item :label="t('memoryView.personaInterval')">{{ t('memoryView.personaIntervalValue', { count: heartbeat?.interval_seconds || '-' }) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never">
        <template #header>{{ t('memoryView.personaLatestBehavior') }}</template>
        <el-empty v-if="!latestBehaviorEvent" :description="t('memoryView.personaNoInterceptedEvents')" />
        <div v-else class="event-section">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('memoryView.personaType')">{{ behaviorTypeLabel(latestBehaviorEvent.type) }}</el-descriptions-item>
            <el-descriptions-item :label="t('memoryView.personaTriggerReason')">{{ latestBehaviorEvent.trigger_reason || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('memoryView.personaEmotion')">{{ behaviorValueLabel(latestBehaviorEvent.emotion_id) }}</el-descriptions-item>
            <el-descriptions-item :label="t('memoryView.personaMotion')">{{ behaviorValueLabel(latestBehaviorEvent.motion_group) }}</el-descriptions-item>
            <el-descriptions-item :label="t('memoryView.personaPrompt')" :span="2">{{ latestBehaviorEvent.prompt || '-' }}</el-descriptions-item>
          </el-descriptions>

          <el-alert :title="latestBehaviorEvent.message || t('memoryView.personaNoMessage')" type="info" :closable="false" />

          <el-alert
            v-if="latestBehaviorEvent.proactive_state?.suppression_reasons?.length"
            :title="t('memoryView.personaSuppression', { reasons: suppressionReasonsText })"
            type="warning"
            show-icon
            :closable="false"
          />

          <div class="button-row">
            <el-button size="small" type="primary" plain :loading="triggeringEmotion" :disabled="triggeringEmotion || !latestBehaviorEvent.emotion_id" @click="triggerEmotion">{{ t('memoryView.personaTriggerEmotion') }}</el-button>
            <el-button size="small" type="primary" plain :loading="triggeringMotion" :disabled="triggeringMotion || !latestBehaviorEvent.motion_group" @click="triggerMotion">{{ t('memoryView.personaTriggerMotion') }}</el-button>
            <el-button size="small" type="success" plain @click="pushPromptToAdvice">{{ t('memoryView.personaPushAdvice') }}</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>{{ t('memoryView.personaRecentBehavior') }}</template>
        <el-empty v-if="!heartbeat?.behavior_events?.length" :description="t('memoryView.personaNoBehaviorEvents')" />
        <div v-else class="event-table-wrap">
          <el-table :data="heartbeat.behavior_events.slice().reverse()" size="small" border>
            <el-table-column prop="at" :label="t('memoryView.personaColumnTime')" width="180" />
            <el-table-column :label="t('memoryView.personaType')" width="160"><template #default="scope">{{ behaviorTypeLabel(scope.row.type) }}</template></el-table-column>
            <el-table-column prop="message" :label="t('memoryView.personaColumnMessage')" min-width="260" show-overflow-tooltip />
          </el-table>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>{{ t('memoryView.personaAdviceTitle') }}</template>
        <div v-if="behaviorSuggestions.length" class="suggestion-list">
          <el-tag v-for="(item, index) in behaviorSuggestions" :key="index" type="info">{{ item }}</el-tag>
        </div>
        <el-empty v-else :description="t('memoryView.personaNoAdvice')" :image-size="56" />
      </el-card>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import 'element-plus/es/components/tag/style/css'
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElMessage,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/descriptions-item/style/css'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import { petControlClient, systemClient } from '@/api/client'
import { useChatStore } from '@/stores/chatStore'
import type { HeartbeatSnapshot } from '@/../shared/agent'
import { describeFailure } from '@/shared/errors/describe-error'

const heartbeat = ref<HeartbeatSnapshot | null>(null)
const behaviorSuggestions = ref<string[]>([])
const loading = ref(false)
const loadError = ref('')
const triggeringEmotion = ref(false)
const triggeringMotion = ref(false)
const { appendLocalAdvice } = useChatStore()
let heartbeatLoadSequence = 0

const latestBehaviorEvent = computed(() => {
  const events = heartbeat.value?.behavior_events
  return Array.isArray(events) && events.length > 0 ? events[events.length - 1] : null
})

const formatAffinity = (value: number | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

const behaviorValueLabels = computed<Record<string, string>>(() => ({
  happy: t('memoryView.behaviorHappy'),
  sad: t('memoryView.behaviorSad'),
  angry: t('memoryView.behaviorAngry'),
  surprised: t('memoryView.behaviorSurprised'),
  neutral: t('memoryView.behaviorNeutral'),
  excited: t('memoryView.behaviorExcited'),
  idle: t('memoryView.behaviorIdle'),
  wave: t('memoryView.behaviorWave'),
  nod: t('memoryView.behaviorNod'),
}))
const behaviorValueLabel = (value: unknown) => {
  const text = typeof value === 'string' ? value.trim() : ''
  return behaviorValueLabels.value[text] || text.replaceAll('_', ' ') || '-'
}

const suppressionReasonLabels = computed<Record<string, string>>(() => ({
  cooldown: t('memoryView.suppressionCooldown'),
  disabled: t('memoryView.suppressionDisabled'),
  quiet_hours: t('memoryView.suppressionQuietHours'),
  no_signal: t('memoryView.suppressionNoSignal'),
  rate_limited: t('memoryView.suppressionRateLimited'),
}))
const suppressionReasonLabel = (value: string) => suppressionReasonLabels.value[value] || value.replaceAll('_', ' ')
const suppressionReasonsText = computed(() => {
  const reasons = latestBehaviorEvent.value?.proactive_state?.suppression_reasons
  if (!Array.isArray(reasons) || reasons.length === 0) return ''
  return reasons.map(suppressionReasonLabel).join(t('memoryView.personaSuppressionSeparator'))
})

const behaviorTypeLabels = computed<Record<string, string>>(() => ({
  proactive_message: t('memoryView.behaviorTypeProactive'),
  scheduled_task: t('memoryView.behaviorTypeScheduled'),
  emotion: t('memoryView.behaviorTypeEmotion'),
  motion: t('memoryView.behaviorTypeMotion'),
  reminder: t('memoryView.behaviorTypeReminder'),
}))
const behaviorTypeLabel = (value: unknown) => {
  const text = typeof value === 'string' ? value : ''
  return behaviorTypeLabels.value[text] || text || t('memoryView.behaviorTypeFallback')
}

const loadHeartbeat = async () => {
  const requestId = ++heartbeatLoadSequence
  loading.value = true
  loadError.value = ''
  try {
    const snapshot = await systemClient.heartbeat()
    if (requestId !== heartbeatLoadSequence) return
    heartbeat.value = snapshot
    const events = snapshot.behavior_events
    behaviorSuggestions.value = Array.isArray(events) ? events.slice(-5).map((item) => item.message).filter(Boolean) : []
  } catch (error) {
    if (requestId !== heartbeatLoadSequence) return
    loadError.value = describeFailure(error, t('memoryView.personaLoadError'))
    console.warn(t('memoryView.personaLoadWarn'), error)
  } finally {
    if (requestId === heartbeatLoadSequence) loading.value = false
  }
}

const triggerEmotion = async () => {
  const emotionId = latestBehaviorEvent.value?.emotion_id
  if (triggeringEmotion.value || !emotionId) {
    return
  }
  triggeringEmotion.value = true
  try {
    await petControlClient.triggerEmotion(emotionId)
    ElMessage.success(t('memoryView.personaEmotionPlayed'))
  } catch {
    ElMessage.warning(t('memoryView.personaEmotionUnavailable'))
  } finally {
    triggeringEmotion.value = false
  }
}

const triggerMotion = async () => {
  const motionGroup = latestBehaviorEvent.value?.motion_group
  if (triggeringMotion.value || !motionGroup) {
    return
  }
  triggeringMotion.value = true
  try {
    await petControlClient.triggerMotion(motionGroup, 0)
    ElMessage.success(t('memoryView.personaMotionPlayed'))
  } catch {
    ElMessage.warning(t('memoryView.personaMotionUnavailable'))
  } finally {
    triggeringMotion.value = false
  }
}

const pushPromptToAdvice = () => {
  if (!latestBehaviorEvent.value?.message) {
    return
  }
  appendLocalAdvice(latestBehaviorEvent.value.message, 'persona-debug')
  ElMessage.success(t('memoryView.personaAdviceAdded'))
}

onMounted(() => {
  void loadHeartbeat()
})
</script>

<style scoped>
.persona-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.panel-toolbar h3 {
  margin: 0 0 4px;
  color: var(--yui-text);
  font-size: 16px;
}

.event-table-wrap {
  min-width: 0;
  overflow-x: auto;
}

.event-table-wrap :deep(.el-table) {
  min-width: 560px;
}

.event-section,
.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.button-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.el-descriptions) {
  border-radius: var(--yui-radius-card);
  overflow: hidden;
}

:deep(.el-table) {
  border-radius: var(--yui-radius-card);
}

@media (max-width: 760px) {
  .panel-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

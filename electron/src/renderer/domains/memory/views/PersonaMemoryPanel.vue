<template>
  <PanelShell :title="t('memoryView.personaTitle')" tone="admin">
    <div class="persona-panel">
      <div class="panel-toolbar">
        <div>
          <h3>{{ t('memoryView.personaCurrentState') }}</h3>
        </div>
        <el-button type="primary" plain :loading="loading" :disabled="loading" @click="loadHeartbeat">{{ t('memoryView.personaRefresh') }}</el-button>
      </div>

      <p role="status">角色：{{ heartbeat?.active_companion?.name || '未知' }} ({{ heartbeat?.active_companion?.id || '-' }}) · 角色配置模型：{{ heartbeat?.active_companion?.model_id || '未知' }} · 当前模型：{{ avatarCapabilities?.modelId || '未知' }} / {{ avatarCapabilities?.modelType || '-' }}</p>
      <el-alert v-if="avatarError" :title="avatarError" type="warning" :closable="false" />
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
        <template #header>{{ t('memoryView.personaLatestBehavior') }} · 历史记录</template>
        <el-empty v-if="!latestBehaviorEvent" :description="t('memoryView.personaNoInterceptedEvents')" />
        <div v-else class="event-section">
          <p>记录于 {{ formatEventTime(latestBehaviorEvent.at) }}</p>
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
            <el-button size="small" type="primary" plain :loading="triggeringEmotion" :disabled="triggeringEmotion || !latestBehaviorEvent.emotion_id || !canTriggerEmotion" :title="canTriggerEmotion ? '向当前模型发送表情' : '能力未确认或角色与当前模型不匹配；请同步角色与模型后重试'" @click="triggerEmotion">{{ t('memoryView.personaTriggerEmotion') }}</el-button>
            <el-button size="small" type="primary" plain :loading="triggeringMotion" :disabled="triggeringMotion || !latestBehaviorEvent.motion_group || !canTriggerMotion" :title="canTriggerMotion ? '向当前模型发送动作' : '当前模型未提供该 motion，或角色与当前模型不匹配；可改用聊天建议'" @click="triggerMotion">{{ t('memoryView.personaTriggerMotion') }}</el-button>
            <el-button size="small" type="success" plain @click="pushPromptToAdvice">{{ t('memoryView.personaPushAdvice') }}</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>{{ t('memoryView.personaRecentBehavior') }}</template>
        <el-empty v-if="!heartbeat?.behavior_events?.length" :description="t('memoryView.personaNoBehaviorEvents')" />
        <div v-else class="event-table-wrap">
          <el-table :data="heartbeat.behavior_events.slice().reverse()" size="small" border>
            <el-table-column :label="t('memoryView.personaColumnTime')" width="180"><template #default="scope">{{ formatEventTime(scope.row.at) }}</template></el-table-column>
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
import { computed, ref } from 'vue'
import { usePanelLifecycle } from '@/app/composables/usePanelLifecycle'
import { useUiCapabilities } from '@/app/composables/useUiCapabilities'
import { petControl } from '@/utils/petControl'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { AVATAR_COMMAND_VERSION, type AvatarAction, type AvatarCapabilitySnapshot } from '@/../shared/avatar-command'
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
import { systemClient } from '@/api/client'
import { useChatStore } from '@/stores/chatStore'
import type { HeartbeatSnapshot } from '@/../shared/agent'
import { describeFailure } from '@/shared/errors/describe-error'

const workspaceStore = useWorkspaceStore()
const uiCapabilities = useUiCapabilities()
const avatarCapabilities = ref<AvatarCapabilitySnapshot | null>(null)
const avatarError = ref('')
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

const avatarMatchesPersona = computed(() => {
  const companion = heartbeat.value?.active_companion
  const avatar = avatarCapabilities.value
  return Boolean(avatar?.modelId && companion && companion.model_id === avatar.modelId
    && (!companion.model_type || companion.model_type === avatar.modelType)
    && (!heartbeat.value?.active_workspace_id || heartbeat.value.active_workspace_id === workspaceStore.activeWorkspaceId))
})
const canTriggerEmotion = computed(() => avatarMatchesPersona.value && avatarCapabilities.value?.actions.affect === true && uiCapabilities.capability('hostHttp').available)
const canTriggerMotion = computed(() => avatarMatchesPersona.value && avatarCapabilities.value?.actions.motion === true
  && avatarCapabilities.value.motions.some((motion) => motion.group === latestBehaviorEvent.value?.motion_group && motion.index === 0)
  && uiCapabilities.capability('hostHttp').available)
const formatEventTime = (value?: string | null) => {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
const loadAvatar = async () => {
  const requestId = heartbeatLoadSequence
  try {
    const result = await petControl.getAvatarCapabilities()
    if (requestId !== heartbeatLoadSequence || !pageLifecycle.active.value) return
    avatarCapabilities.value = result.capabilities
    avatarError.value = ''
  } catch (error) {
    if (requestId !== heartbeatLoadSequence) return
    avatarCapabilities.value = null
    avatarError.value = describeFailure(error, '当前模型能力读取失败')
  }
}

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
    const [snapshot] = await Promise.all([systemClient.heartbeat(), loadAvatar(), uiCapabilities.refresh()])
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

const replayAvatarAction = async (action: AvatarAction) => {
  const capabilities = avatarCapabilities.value
  if (!pageLifecycle.active.value || !capabilities || !avatarMatchesPersona.value) return
  const sequence = heartbeatLoadSequence
  const commandId = `persona-${crypto.randomUUID()}`
  const result = await petControl.triggerAvatarCommand({
    version: AVATAR_COMMAND_VERSION,
    id: commandId,
    streamId: 'ui-persona-memory',
    sequence: Date.now(),
    issuedAt: Date.now(),
    capabilityRevision: capabilities.revision,
    priority: 60,
    interrupt: 'replace',
    actions: [action],
  })
  if (sequence !== heartbeatLoadSequence || !pageLifecycle.active.value) return
  if (!result || result.commandId !== commandId) throw new Error('动作响应身份不匹配；结果未知，请先同步模型状态。')
  if (result.status === 'completed') ElMessage.success('当前模型动作已完成。')
  else if (result.status === 'accepted' || result.status === 'started') ElMessage.info('动作请求已接受；渲染完成以舞台反馈为准。')
  else ElMessage.warning(result.message || `动作未完成：${result.status}`)
}

const triggerEmotion = async () => {
  const emotionId = latestBehaviorEvent.value?.emotion_id
  if (triggeringEmotion.value || triggeringMotion.value || !emotionId || !canTriggerEmotion.value) return
  triggeringEmotion.value = true
  try {
    await replayAvatarAction({ type: 'affect', emotion: emotionId })
  } catch (error) {
    ElMessage.warning(describeFailure(error, t('memoryView.personaEmotionUnavailable')))
  } finally { triggeringEmotion.value = false }
}

const triggerMotion = async () => {
  const motionGroup = latestBehaviorEvent.value?.motion_group
  if (triggeringMotion.value || triggeringEmotion.value || !motionGroup || !canTriggerMotion.value) return
  triggeringMotion.value = true
  try {
    await replayAvatarAction({ type: 'motion', group: motionGroup, index: 0 })
  } catch (error) {
    ElMessage.warning(describeFailure(error, t('memoryView.personaMotionUnavailable')))
  } finally { triggeringMotion.value = false }
}

const pushPromptToAdvice = () => {
  if (!latestBehaviorEvent.value?.message) {
    return
  }
  appendLocalAdvice(latestBehaviorEvent.value.message, 'persona-debug')
  ElMessage.success(t('memoryView.personaAdviceAdded'))
}

const pageLifecycle = usePanelLifecycle(loadHeartbeat, () => {
  heartbeatLoadSequence += 1
  loading.value = false
  avatarCapabilities.value = null
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

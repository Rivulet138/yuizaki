<template>
  <PanelShell title="行为记忆调试" tone="admin">
    <div class="persona-panel">
      <div class="panel-toolbar">
        <div>
          <h3>Heartbeat Snapshot</h3>
        </div>
        <el-button type="primary" plain :loading="loading" :disabled="loading" @click="loadHeartbeat">刷新状态</el-button>
      </div>

      <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="false" />

      <el-card shadow="never">
        <template #header>Persona 状态</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="心情">{{ heartbeat?.persona?.mood || '-' }}</el-descriptions-item>
          <el-descriptions-item label="精力">{{ heartbeat?.persona?.energy || '-' }}</el-descriptions-item>
          <el-descriptions-item label="亲密度">{{ heartbeat?.persona?.affinity?.toFixed(3) || '-' }}</el-descriptions-item>
          <el-descriptions-item label="运行状态">{{ heartbeat?.running ? '运行中' : '已停止' }}</el-descriptions-item>
          <el-descriptions-item label="心跳次数">{{ heartbeat?.tick_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="间隔">{{ heartbeat?.interval_seconds || '-' }} 秒</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never">
        <template #header>最近行为事件</template>
        <el-empty v-if="!latestBehaviorEvent" description="暂无截获的行为事件" />
        <div v-else class="event-section">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="类型">{{ latestBehaviorEvent.type }}</el-descriptions-item>
            <el-descriptions-item label="触发原因">{{ latestBehaviorEvent.trigger_reason || '-' }}</el-descriptions-item>
            <el-descriptions-item label="情绪">{{ latestBehaviorEvent.emotion_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="动作">{{ latestBehaviorEvent.motion_group || '-' }}</el-descriptions-item>
            <el-descriptions-item label="动作提示" :span="2">{{ latestBehaviorEvent.prompt || '-' }}</el-descriptions-item>
          </el-descriptions>

          <el-alert :title="latestBehaviorEvent.message || '(无消息体)'" type="info" :closable="false" />

          <el-alert
            v-if="latestBehaviorEvent.proactive_state?.suppression_reasons?.length"
            :title="latestBehaviorEvent.proactive_state.suppression_reasons.join(', ')"
            type="warning"
            show-icon
            :closable="false"
          />

          <div class="button-row">
            <el-button size="small" type="primary" plain :loading="triggeringEmotion" :disabled="triggeringEmotion || !latestBehaviorEvent.emotion_id" @click="triggerEmotion">触发表情</el-button>
            <el-button size="small" type="primary" plain :loading="triggeringMotion" :disabled="triggeringMotion || !latestBehaviorEvent.motion_group" @click="triggerMotion">触发动作</el-button>
            <el-button size="small" type="success" plain @click="pushPromptToAdvice">加入聊天建议</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>行为事件日志</template>
        <el-empty v-if="!heartbeat?.behavior_events?.length" description="暂无行为事件" />
        <el-table v-else :data="heartbeat.behavior_events.slice().reverse()" size="small" border>
          <el-table-column prop="at" label="时间" width="180" />
          <el-table-column prop="type" label="类型" width="160" />
          <el-table-column prop="message" label="消息" min-width="260" show-overflow-tooltip />
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header>行为建议</template>
        <div v-if="behaviorSuggestions.length" class="suggestion-list">
          <el-tag v-for="(item, index) in behaviorSuggestions" :key="index" type="info">{{ item }}</el-tag>
        </div>
        <el-empty v-else description="暂无行为建议" :image-size="56" />
      </el-card>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { petControlClient, systemClient } from '@/api/client'
import { useChatStore } from '@/stores/chatStore'
import type { HeartbeatSnapshot } from '@/../shared/agent'

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
    loadError.value = error instanceof Error ? error.message : '无法读取 Heartbeat 状态'
    console.warn('加载 Heartbeat 状态失败', error)
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
    ElMessage.success(`已触发表情 ${emotionId}`)
  } catch {
    ElMessage.warning('当前行为事件未映射到可用表情预设')
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
    ElMessage.success(`已触发动作 ${motionGroup}`)
  } catch {
    ElMessage.warning('当前行为事件未映射到可用动作组')
  } finally {
    triggeringMotion.value = false
  }
}

const pushPromptToAdvice = () => {
  if (!latestBehaviorEvent.value?.message) {
    return
  }
  appendLocalAdvice(latestBehaviorEvent.value.message, 'persona-debug')
  ElMessage.success('已加入聊天建议')
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

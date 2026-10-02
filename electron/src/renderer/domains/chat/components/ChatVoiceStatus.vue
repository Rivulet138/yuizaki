<template>
  <div class="voice-console">
    <div class="voice-console__controls">
      <el-segmented :model-value="mode" :options="modeOptions" size="small" @change="$emit('update:mode', String($event))" />
      <button
        v-if="mode === 'hold'"
        type="button"
        class="hold-to-talk"
        :class="{ active: holdActive || recording }"
        :disabled="!connected"
        :title="shortcutTitle"
        @pointerdown.prevent="$emit('hold-pointer-down', $event)"
        @pointerup.prevent="$emit('hold-pointer-up', $event)"
        @pointercancel.prevent="$emit('hold-pointer-up', $event)"
        @keydown.space.prevent="$emit('begin-hold')"
        @keyup.space.prevent="$emit('end-hold')"
      >
        <el-icon><Microphone /></el-icon>
        <span>{{ recording ? '松开发送' : '按住说话' }}</span>
      </button>
      <button
        v-else
        type="button"
        class="hold-to-talk"
        :class="{ active: recording }"
        :disabled="!connected"
        :title="shortcutTitle"
        @click="$emit('toggle-mic')"
      >
        <el-icon><Microphone /></el-icon>
        <span>{{ recording ? '结束录音' : '语音输入' }}</span>
      </button>
      <button class="voice-stop-button" type="button" :disabled="!interruptible" :aria-label="interruptibleLabel" :title="interruptibleLabel" @click="$emit('interrupt')">
        <el-icon><Mute /></el-icon>
      </button>
      <button
        v-if="showRecoveryAction"
        class="voice-retry-button"
        type="button"
        title="重连实时语音"
        aria-label="重连实时语音"
        @click="$emit('retry-realtime')"
      >
        <el-icon><Refresh /></el-icon>
        <span>重连语音</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElIcon } from 'element-plus'
import 'element-plus/es/components/icon/style/css'
import { computed } from 'vue'
import { ElSegmented } from 'element-plus'
import 'element-plus/es/components/segmented/style/css'
import { Microphone, Mute, Refresh } from '@element-plus/icons-vue'

const props = defineProps<{
  recording: boolean
  mode: string
  modeOptions: Array<{ label: string; value: string }>
  holdActive: boolean
  connected: boolean
  shortcutTitle: string
  interruptible: boolean
  showRecoveryAction: boolean
}>()

const interruptibleLabel = computed(() => props.interruptible ? '停止当前语音响应' : '没有可停止的语音响应')

defineEmits<{
  'update:mode': [mode: string]
  'hold-pointer-down': [event: PointerEvent]
  'hold-pointer-up': [event: PointerEvent]
  'begin-hold': []
  'end-hold': []
  'toggle-mic': []
  interrupt: []
  'retry-realtime': []
}>()
</script>

<style scoped>
.voice-console {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 10px 12px;
}

.voice-console__controls {
  display: flex;
  min-width: 0;
  align-items: center;
  width: 100%;
  gap: 8px;
}

.voice-stop-button {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--yui-border);
  border-radius: 50%;
  background: var(--yui-surface-raised);
  color: var(--yui-accent);
}

.voice-retry-button {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  padding: 0 10px;
  cursor: pointer;
}

.voice-retry-button:hover,
.voice-retry-button:focus-visible {
  border-color: var(--yui-accent);
  color: var(--yui-accent);
}

.hold-to-talk {
  min-height: 34px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  padding: 0 10px;
  cursor: pointer;
}

.hold-to-talk.active {
  border-color: var(--yui-accent);
  color: var(--yui-accent);
}

.hold-to-talk:disabled,
.voice-stop-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

button:focus-visible {
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 900px) {
  .voice-console {
    align-items: stretch;
    flex-direction: column;
  }

  .voice-console__controls {
    flex-wrap: wrap;
  }
}
</style>

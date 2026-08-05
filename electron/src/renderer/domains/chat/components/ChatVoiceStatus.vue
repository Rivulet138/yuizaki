<template>
  <div class="voice-console">
    <div class="voice-console__main">
      <div class="voice-status-badge" :class="statusClass">
        <el-icon><Headset /></el-icon>
      </div>
      <div class="voice-status-stack">
        <div class="voice-status-line">
          <strong>{{ statusText }}</strong>
          <small>{{ pipelineText }}</small>
          <small v-if="recording && processingText">{{ processingText }}</small>
          <small v-if="latencySummary" class="voice-latency-summary">{{ latencySummary }}</small>
        </div>
        <div class="voice-meter" aria-label="麦克风电平">
          <span v-for="level in meterBars" :key="level" :class="{ active: levelPercent >= level }"></span>
        </div>
      </div>
    </div>

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
      <button class="voice-stop-button" type="button" :disabled="!ttsPlaying" aria-label="停止语音播放" @click="$emit('interrupt')">
        <el-icon><Mute /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Headset, Microphone, Mute } from '@element-plus/icons-vue'

defineProps<{
  statusClass: string
  statusText: string
  pipelineText: string
  processingText: string
  latencySummary: string
  recording: boolean
  meterBars: number[]
  levelPercent: number
  mode: string
  modeOptions: Array<{ label: string; value: string }>
  holdActive: boolean
  connected: boolean
  shortcutTitle: string
  ttsPlaying: boolean
}>()

defineEmits<{
  'update:mode': [mode: string]
  'hold-pointer-down': [event: PointerEvent]
  'hold-pointer-up': [event: PointerEvent]
  'begin-hold': []
  'end-hold': []
  'toggle-mic': []
  interrupt: []
}>()
</script>

<style scoped>
.voice-console {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 10px 12px;
}

.voice-console__main,
.voice-console__controls,
.voice-status-stack,
.voice-status-line,
.voice-meter {
  display: flex;
  min-width: 0;
  align-items: center;
}

.voice-console__main {
  flex: 1;
  gap: 10px;
}

.voice-console__controls {
  gap: 8px;
}

.voice-status-stack,
.voice-status-line {
  align-items: flex-start;
  flex-direction: column;
}

.voice-status-line strong {
  color: var(--yui-text);
  font-size: 13px;
}

.voice-status-line small {
  color: var(--yui-muted);
  font-size: 11px;
}

.voice-status-badge,
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

.voice-status-badge.recording {
  border-color: color-mix(in srgb, var(--yui-danger) 28%, var(--yui-border));
  color: var(--yui-danger);
}

.voice-status-badge.speaking {
  border-color: color-mix(in srgb, var(--yui-accent) 28%, var(--yui-border));
  background: var(--yui-accent-soft);
}

.voice-status-badge.offline,
.voice-status-badge.error {
  color: var(--yui-muted);
}

.voice-meter {
  gap: 3px;
  margin-top: 5px;
}

.voice-meter span {
  width: 3px;
  height: 10px;
  border-radius: 2px;
  background: var(--yui-border-strong);
}

.voice-meter span.active {
  background: var(--yui-accent);
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

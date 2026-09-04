<template>
  <div v-if="statusText" class="composer-status-line" :class="statusTone" role="status" aria-live="polite">
    <span class="composer-status-dot" aria-hidden="true"></span>
    <span>{{ statusText }}</span>
    <button
      v-if="showRecoveryAction"
      class="composer-status-retry"
      type="button"
      title="重连实时语音"
      aria-label="重连实时语音"
      @click="emit('retry')"
    >
      <el-icon><Refresh /></el-icon>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'

const props = withDefaults(defineProps<{
  connected: boolean
  generating: boolean
  recording: boolean
  ttsPlaying: boolean
  showRecoveryAction?: boolean
}>(), {
  showRecoveryAction: false,
})
const emit = defineEmits<{ retry: [] }>()

const { t } = useI18n()

const statusKey = computed(() => {
  if (props.recording) return 'chat.composerStatus.recording'
  if (props.generating) return 'chat.composerStatus.generating'
  if (props.ttsPlaying) return 'chat.composerStatus.playing'
  if (!props.connected) return 'chat.status.channelOffline'
  return ''
})
const statusText = computed(() => statusKey.value ? t(statusKey.value) : '')
const statusTone = computed(() => ({
  'is-unavailable': !props.connected,
  'is-active': props.connected && Boolean(statusKey.value),
}))
</script>

<style scoped>
.composer-status-line {
  display: inline-flex;
  width: fit-content;
  min-height: 20px;
  align-items: center;
  gap: 7px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 20px;
}

.composer-status-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.composer-status-line.is-active {
  color: var(--yui-accent);
}

.composer-status-line.is-unavailable {
  color: var(--yui-muted);
}

.composer-status-retry {
  display: inline-grid;
  width: 22px;
  height: 22px;
  padding: 0;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 6px;
  color: inherit;
  background: transparent;
  cursor: pointer;
}

.composer-status-retry:hover,
.composer-status-retry:focus-visible {
  color: var(--yui-chat-text);
  background: var(--yui-chat-hover);
}

.composer-status-retry:focus-visible {
  outline: 2px solid var(--yui-chat-focus);
  outline-offset: 2px;
}
</style>

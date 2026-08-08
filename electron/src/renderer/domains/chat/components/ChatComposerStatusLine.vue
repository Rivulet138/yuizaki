<template>
  <div v-if="statusText" class="composer-status-line" :class="statusTone" role="status" aria-live="polite">
    <span class="composer-status-dot" aria-hidden="true"></span>
    <span>{{ statusText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  connected: boolean
  generating: boolean
  recording: boolean
  ttsPlaying: boolean
}>()

const { t } = useI18n()

const statusKey = computed(() => {
  if (!props.connected) return 'chat.composerStatus.unavailable'
  if (props.recording) return 'chat.composerStatus.recording'
  if (props.generating) return 'chat.composerStatus.generating'
  if (props.ttsPlaying) return 'chat.composerStatus.playing'
  return ''
})
const statusText = computed(() => statusKey.value ? t(statusKey.value) : '')
const statusTone = computed(() => ({
  'is-error': !props.connected,
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

.composer-status-line.is-error {
  color: var(--yui-danger, #b91c1c);
}
</style>

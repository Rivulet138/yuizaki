<template>
  <div class="composer-meta-line" :aria-label="t('chat.composerStatus.aria')">
    <span class="composer-meta-chip" :class="{ ready: connected }">
      {{ connected ? t('chat.composerStatus.connected') : t('chat.composerStatus.connecting') }}
    </span>
    <span v-if="webSearchEnabled" class="composer-meta-chip is-active">{{ t('chat.composerStatus.webSearch') }}</span>
    <span v-if="mcpEnabled" class="composer-meta-chip is-active">MCP</span>
    <span class="composer-meta-value">{{ modelLabel }}</span>
    <span>{{ petLinkEnabled ? t('chat.composerStatus.petLinked') : t('chat.composerStatus.standalone') }}</span>
    <span class="composer-meta-chip" :class="{ 'is-active': ttsEnabled }">{{ ttsEnabled ? 'TTS' : t('chat.composerStatus.muted') }}</span>
    <span>{{ voicePermissionText }}</span>
    <span>{{ t('chat.composerStatus.tokens', { count: inputTokens }) }}</span>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'

const { t } = useI18n()

defineProps<{
  connected: boolean
  webSearchEnabled: boolean
  mcpEnabled: boolean
  modelLabel: string
  petLinkEnabled: boolean
  ttsEnabled: boolean
  voicePermissionText: string
  inputTokens: number
}>()
</script>

<style scoped>
.composer-meta-line {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  min-height: 16px;
  order: 4;
  color: var(--yui-muted);
  font-size: 11px;
}

.composer-meta-chip {
  border: 1px solid var(--yui-border);
  border-radius: 6px;
  background: var(--yui-surface-muted);
  padding: 2px 6px;
}

.composer-meta-chip.ready,
.composer-meta-chip.is-active {
  border-color: color-mix(in srgb, var(--yui-accent) 20%, transparent);
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
}

.composer-meta-value {
  max-width: 128px;
  overflow: hidden;
  color: var(--yui-text);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

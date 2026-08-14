<template>
  <div v-if="visible" class="chat-playback-bar" role="status" aria-live="polite">
    <span class="chat-playback-bar__icon" aria-hidden="true">
      <el-icon><Headset /></el-icon>
    </span>
    <div class="chat-playback-bar__copy">
      <strong>{{ playing ? t('chat.playback.playing') : t('chat.playback.processing') }}</strong>
      <span v-if="text">{{ text }}</span>
    </div>
    <div class="chat-playback-bar__actions">
      <button
        class="chat-playback-bar__pet"
        :class="{ active: petLinkEnabled }"
        type="button"
        :aria-pressed="petLinkEnabled"
        :title="petLinkEnabled ? t('chat.playback.petLink.disable') : t('chat.playback.petLink.enable')"
        @click="$emit('toggle-pet-link', !petLinkEnabled)"
      >
        <el-icon><StarFilled /></el-icon>
        <span>{{ t('chat.playback.pet') }}</span>
      </button>
      <button
        class="chat-playback-bar__stop"
        type="button"
        :disabled="!playing && !speaking"
        :aria-label="t('chat.playback.stop')"
        :title="t('chat.playback.stop')"
        @click="$emit('interrupt')"
      >
        <el-icon><Mute /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Headset, Mute, StarFilled } from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'

const props = defineProps<{
  playing: boolean
  speaking: boolean
  petLinkEnabled: boolean
  text?: string
}>()

const { t } = useI18n()

defineEmits<{
  interrupt: []
  'toggle-pet-link': [enabled: boolean]
}>()

const visible = computed(() => props.playing || props.speaking)
</script>

<style scoped>
.chat-playback-bar {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  padding: 7px 9px;
}

.chat-playback-bar__icon,
.chat-playback-bar__stop,
.chat-playback-bar__pet {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
}

.chat-playback-bar__icon {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
}

.chat-playback-bar__copy {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 1px;
}

.chat-playback-bar__copy strong {
  font-size: 12px;
  line-height: 1.3;
}

.chat-playback-bar__copy span {
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-playback-bar__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
}

.chat-playback-bar__pet,
.chat-playback-bar__stop {
  min-height: 30px;
  border: 1px solid var(--yui-border);
  border-radius: 7px;
  background: var(--yui-surface-raised);
  color: var(--yui-muted);
  cursor: pointer;
  padding: 0 8px;
}

.chat-playback-bar__pet {
  gap: 5px;
  font-size: 11px;
}

.chat-playback-bar__pet.active {
  border-color: color-mix(in srgb, var(--yui-accent) 34%, var(--yui-border));
  color: var(--yui-accent);
}

.chat-playback-bar__stop {
  width: 30px;
  padding: 0;
}

.chat-playback-bar__stop:not(:disabled):hover,
.chat-playback-bar__pet:hover {
  color: var(--yui-text);
}

.chat-playback-bar__stop:disabled {
  cursor: default;
  opacity: 0.42;
}

button:focus-visible {
  outline: 2px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 520px) {
  .chat-playback-bar__pet span {
    display: none;
  }
}
</style>

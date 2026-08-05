<template>
  <section class="quick-actions" :aria-label="actionsTitle">
    <router-link class="command is-primary" :to="chatPath" data-testid="companion-talk-action">
      <el-icon><ChatDotRound /></el-icon>
      <span>{{ talkLabel }}</span>
    </router-link>
    <button class="command" type="button" @click="$emit('toggle-mute')">
      <el-icon><component :is="muted ? Microphone : MuteNotification" /></el-icon>
      <span>{{ muted ? unmuteLabel : muteLabel }}</span>
    </button>
    <button class="command" type="button" :disabled="!canInterrupt" @click="$emit('interrupt')">
      <el-icon><VideoPause /></el-icon>
      <span>{{ interruptLabel }}</span>
    </button>

    <label class="setting-command">
      <span>{{ dndLabel }}</span>
      <el-switch data-testid="companion-dnd-toggle" :model-value="dnd" :loading="dndLoading" @change="$emit('set-dnd', Boolean($event))" />
    </label>
    <label class="setting-command">
      <span>{{ proactivityLabel }}</span>
      <el-select
        data-testid="companion-proactivity-preset"
        :model-value="proactivityPreset"
        size="small"
        @change="$emit('set-proactivity', String($event))"
      >
        <el-option :label="conservativeLabel" value="conservative" />
        <el-option :label="standardLabel" value="standard" />
      </el-select>
    </label>
  </section>
</template>

<script setup lang="ts">
import { ChatDotRound, Microphone, MuteNotification, VideoPause } from '@element-plus/icons-vue'

defineProps<{
  actionsTitle: string
  chatPath: string
  talkLabel: string
  muteLabel: string
  unmuteLabel: string
  interruptLabel: string
  canInterrupt: boolean
  muted: boolean
  dnd: boolean
  dndLabel: string
  dndLoading: boolean
  proactivityLabel: string
  proactivityPreset: string
  conservativeLabel: string
  standardLabel: string
}>()

defineEmits<{
  interrupt: []
  'toggle-mute': []
  'set-dnd': [enabled: boolean]
  'set-proactivity': [preset: string]
}>()
</script>

<style scoped>
.quick-actions {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.command,
.setting-command {
  min-width: 0;
  min-height: 72px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
}

.command {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  font: inherit;
  font-size: 13px;
  font-weight: 760;
  text-decoration: none;
  cursor: pointer;
}

.command.is-primary {
  border-color: var(--yui-accent);
  background: var(--yui-accent);
  color: #fff;
}

.command:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.setting-command {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 720;
}

.command:hover:not(:disabled) {
  border-color: var(--yui-border-strong);
}

.command:focus-visible,
.setting-command:focus-within,
a:focus-visible,
button:focus-visible {
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 1080px) {
  .quick-actions {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .quick-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .setting-command {
    grid-column: span 2;
  }
}
</style>

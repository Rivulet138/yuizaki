<template>
  <aside class="runtime-environment-strip" :class="`tone-${tone}`" role="status" aria-live="polite">
    <div class="runtime-environment-copy">
      <el-icon class="runtime-environment-icon">
        <Monitor v-if="kind === 'browser'" />
        <WarningFilled v-else />
      </el-icon>
      <div>
        <strong>{{ title }}</strong>
        <span>{{ detail }}</span>
      </div>
    </div>
    <div class="runtime-environment-actions">
      <el-button size="small" plain @click="$emit('open-checks')">运行检查</el-button>
      <el-button v-if="retryable" size="small" type="primary" @click="$emit('retry')">重试连接</el-button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { Monitor, WarningFilled } from '@element-plus/icons-vue'

defineProps<{
  kind: 'browser' | 'offline' | 'degraded'
  tone: 'info' | 'warning' | 'danger'
  title: string
  detail: string
  retryable?: boolean
}>()

defineEmits<{
  (event: 'open-checks'): void
  (event: 'retry'): void
}>()
</script>

<style scoped>
.runtime-environment-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
  padding: 8px 10px 8px 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control, 6px);
  background: var(--yui-surface);
  box-sizing: border-box;
}

.runtime-environment-strip.tone-info {
  border-color: color-mix(in srgb, var(--yui-accent) 28%, var(--yui-border));
  background: color-mix(in srgb, var(--yui-accent) 7%, var(--yui-surface));
}

.runtime-environment-strip.tone-warning {
  border-color: color-mix(in srgb, var(--yui-warning, #d97706) 42%, var(--yui-border));
  background: var(--yui-warning-soft);
}

.runtime-environment-strip.tone-danger {
  border-color: color-mix(in srgb, var(--yui-danger, #dc2626) 42%, var(--yui-border));
  background: var(--yui-danger-soft);
}

.runtime-environment-copy,
.runtime-environment-actions {
  display: flex;
  align-items: center;
  min-width: 0;
}

.runtime-environment-copy {
  gap: 10px;
}

.runtime-environment-copy > div {
  min-width: 0;
}

.runtime-environment-copy strong,
.runtime-environment-copy span {
  display: block;
}

.runtime-environment-copy strong {
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.35;
}

.runtime-environment-copy span {
  margin-top: 2px;
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-environment-icon {
  flex: 0 0 auto;
  color: var(--yui-text);
  font-size: 18px;
}

.runtime-environment-actions {
  flex: 0 0 auto;
  gap: 8px;
}

@media (max-width: 760px) {
  .runtime-environment-strip {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .runtime-environment-copy span {
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
  }

  .runtime-environment-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>

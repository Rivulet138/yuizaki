<template>
  <section class="panel-shell" :class="[`panel-shell--${tone}`, `panel-shell--${density}`, { 'panel-shell--minimal': minimal }]">
    <header v-if="!minimal" class="panel-shell__header">
      <div class="panel-shell__title-group">
        <div v-if="$slots.status" class="panel-shell__status-row">
          <slot name="status" />
        </div>
        <h2 class="panel-shell__title">{{ title }}</h2>
        <p v-if="subtitle" class="panel-shell__subtitle">{{ subtitle }}</p>
      </div>

      <div v-if="$slots.actions" class="panel-shell__actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="panel-shell__body">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  subtitle?: string
  tone?: 'companion' | 'admin' | 'neutral'
  density?: 'comfortable' | 'compact'
  minimal?: boolean
}>(), {
  tone: 'neutral',
  density: 'comfortable',
  minimal: false,
})

</script>

<style scoped>
.panel-shell {
  position: relative;
  padding: 0;
  border: 1px solid var(--yui-panel-outline, var(--yui-border));
  border-radius: var(--yui-radius-panel, 18px);
  background: var(--yui-panel-surface, var(--yui-surface));
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow, var(--yui-shadow-card));
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.panel-shell--minimal {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.panel-shell:not(.panel-shell--minimal):focus-within {
  border-color: var(--yui-panel-outline-strong, var(--yui-border-strong));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--yui-accent) 14%, transparent), var(--yui-panel-shadow, var(--yui-shadow-card));
}

.panel-shell--compact {
  gap: 8px;
}

.panel-shell__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--yui-border);
  flex-shrink: 0;
}

.panel-shell__title-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.panel-shell__status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-shell__title {
  margin: 0;
  font-family: var(--yui-font-display);
  font-size: 17px;
  font-weight: 700;
  color: var(--yui-text);
  line-height: 1.25;
}

.panel-shell__subtitle {
  max-width: 68ch;
  margin: 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.panel-shell__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.panel-shell--compact .panel-shell__body {
  gap: 10px;
}

.panel-shell--minimal .panel-shell__body {
  gap: 0;
  padding-right: 0;
}

.panel-shell__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.panel-shell__actions :deep(.el-button),
.panel-shell__actions :deep(button) {
  min-height: 30px;
}

@media (max-width: 900px) {
  .panel-shell__header {
    flex-direction: column;
    gap: 12px;
  }

  .panel-shell__actions {
    width: 100%;
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .panel-shell__body {
    padding-right: 0;
  }
}

/* 优化内层滚动条 */
.panel-shell__body::-webkit-scrollbar {
  width: 6px;
}

.panel-shell__body::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--yui-muted) 32%, transparent);
  border-radius: 4px;
}

.panel-shell__body::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--yui-muted) 52%, transparent);
}
</style>

<template>
  <div class="settings-section-header">
    <div class="settings-section-heading">
      <h3>{{ title }}</h3>
      <div v-if="$slots.status" class="settings-section-status">
        <slot name="status" />
      </div>
    </div>
    <div v-if="$slots.actions" class="settings-section-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
}>()
</script>

<style scoped>
.settings-section-header,
.settings-section-heading,
.settings-section-actions {
  display: flex;
  min-width: 0;
  align-items: center;
}

.settings-section-header {
  justify-content: space-between;
  gap: 12px;
}

.settings-section-heading {
  flex-wrap: wrap;
  gap: 8px;
}

.settings-section-heading h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 15px;
  font-weight: 700;
}

.settings-section-status,
.settings-section-actions {
  gap: 8px;
}

@media (max-width: 760px) {
  .settings-section-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .settings-section-actions {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>

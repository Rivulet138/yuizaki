<template>
  <section
    v-if="visible"
    class="runtime-feedback"
    data-testid="settings-runtime-feedback"
    role="status"
    aria-live="polite"
    :aria-label="t('settings.status.runtimeApplication')"
    :aria-busy="loading"
  >
    <strong>{{ t('settings.status.runtimeApplication') }}</strong>
    <p v-if="loading && !failed.length && !pending.length && !statusError && !retryError">{{ t('ui.loading') }}</p>
    <p v-if="failed.length" class="runtime-feedback-error">
      {{ t('settings.status.runtimeFailed', { items: labels(failed) }) }}
    </p>
    <ul v-if="failed.length" class="runtime-feedback-sections">
      <li
        v-for="[section, state] in failed"
        :key="section"
        :data-section="section"
        :data-target-revision="state.target_revision"
      >
        <span>{{ sectionLabel(section) }}</span>
        <code>r{{ state.target_revision }}</code>
        <span v-if="state.error" class="runtime-feedback-error">{{ state.error }}</span>
      </li>
    </ul>
    <p v-if="pending.length">
      {{ t('settings.status.runtimePending', { items: labels(pending) }) }}
    </p>
    <p v-if="statusError" class="runtime-feedback-error" role="alert">
      {{ t('settings.status.runtimeUnknown') }} {{ statusError }}
    </p>
    <p v-if="retryError" class="runtime-feedback-error" role="alert">{{ retryError }}</p>
    <div class="runtime-feedback-actions">
      <button type="button" :disabled="loading" @click="refresh">
        {{ t('settings.status.refreshRuntime') }}
      </button>
      <button v-if="failed.length" type="button" :disabled="loading" @click="retry">
        {{ t('settings.status.retryRuntime') }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RuntimeReloadSection, RuntimeReloadStatusResponse } from '@/api/clients/settings-client'
import { t } from '@/i18n'

const props = defineProps<{
  status: RuntimeReloadStatusResponse | null
  statusError: string
  retryError: string
  loading: boolean
  sectionLabels?: Record<string, string>
}>()

const emit = defineEmits<{
  retry: [targets: Record<string, number>]
  refresh: []
}>()

const entries = computed(() => Object.entries(props.status?.sections ?? {}))
const failed = computed(() => entries.value.filter(([, state]) => state.state === 'failed' || state.state === 'unavailable'))
const pending = computed(() => entries.value.filter(([, state]) => state.state === 'pending' || state.state === 'applying'))
const visible = computed(() => Boolean(props.loading || failed.value.length || pending.value.length || props.statusError || props.retryError))
const sectionLabel = (section: string) => props.sectionLabels?.[section] || section.toUpperCase()
const labels = (sections: [string, RuntimeReloadSection][]) => sections.map(([section]) => sectionLabel(section)).join(' / ')

const refresh = () => {
  if (!props.loading) emit('refresh')
}
const retry = () => {
  if (!props.loading && failed.value.length) {
    emit('retry', Object.fromEntries(failed.value.map(([section, state]) => [section, state.target_revision])))
  }
}
</script>

<style scoped>
.runtime-feedback {
  padding: 14px 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  background: var(--el-bg-color-overlay);
  color: var(--el-text-color-primary);
  overflow-wrap: anywhere;
}

.runtime-feedback p {
  margin: 8px 0;
}

.runtime-feedback-error {
  color: var(--el-color-danger);
}

.runtime-feedback-sections {
  margin: 8px 0;
  padding-inline-start: 20px;
}

.runtime-feedback-sections code {
  margin-inline: 8px;
}

.runtime-feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.runtime-feedback-actions button {
  padding: 6px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-primary);
  font: inherit;
  cursor: pointer;
}

.runtime-feedback-actions button:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>

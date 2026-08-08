<template>
  <el-card shadow="never">
    <template #header>
      <SettingsSectionHeader :title="t('settings.svc.service')">
        <template #status>
          <el-tag :type="hasEndpoint ? 'success' : 'info'" size="small">
            {{ hasEndpoint ? t('common.configured') : t('common.optional') }}
          </el-tag>
        </template>
        <template #actions>
          <el-button data-testid="discover-svc" plain :loading="discoveryLoading" @click="$emit('discover-local')">
            <el-icon><Connection /></el-icon>
            {{ t('settings.discovery.detectLocal') }}
          </el-button>
        </template>
      </SettingsSectionHeader>
    </template>

    <el-alert
      v-if="discoveryError"
      class="discovery-error"
      :title="discoveryError"
      type="error"
      show-icon
      :closable="false"
    />

    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="t('settings.svc.provider')">
        <el-select :model-value="modelValue.provider" class="full-width" @change="emitField('provider', $event)">
          <el-option label="SoulX-Singer-SVC Service" value="soulx-service" />
          <el-option :label="t('common.disabled')" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('settings.svc.baseUrl')">
        <el-input :model-value="modelValue.base_url" @change="emitField('base_url', $event)" />
      </el-form-item>
      <div class="form-grid">
        <el-form-item :label="t('settings.svc.referenceAudioId')">
          <el-input-number :model-value="modelValue.speaker_id" :min="0" controls-position="right" @change="emitField('speaker_id', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.svc.pitch')">
          <el-input-number :model-value="modelValue.pitch" :min="-36" :max="36" controls-position="right" @change="emitField('pitch', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.svc.timeout')">
          <el-input-number :model-value="modelValue.timeout" :min="10" :max="900" controls-position="right" @change="emitField('timeout', $event)" />
        </el-form-item>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Connection } from '@element-plus/icons-vue'

import { t } from '@/i18n'
import SettingsSectionHeader from './SettingsSectionHeader.vue'

export type SvcSettings = {
  provider: string
  base_url: string
  speaker_id: number
  pitch: number
  timeout: number
}

const props = defineProps<{
  modelValue: SvcSettings
  discoveryLoading: boolean
  discoveryError?: string | null
}>()

const emit = defineEmits<{
  'update-field': [field: keyof SvcSettings, value: string | number]
  'discover-local': []
}>()

const hasEndpoint = computed(() => props.modelValue.provider !== 'disabled' && Boolean(props.modelValue.base_url.trim()))

const emitField = (field: keyof SvcSettings, value: unknown) => {
  if (typeof value === 'string' || typeof value === 'number') {
    emit('update-field', field, value)
  }
}
</script>

<style scoped>
.discovery-error { margin-bottom: 14px; }

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;
}

.full-width { width: 100%; }

@media (max-width: 900px) {
  .form-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>

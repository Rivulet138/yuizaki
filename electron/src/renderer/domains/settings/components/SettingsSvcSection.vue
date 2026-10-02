<template>
  <el-card shadow="never">
    <template #header>
      <SettingsSectionHeader :title="t('settings.svc.service')">
        <template #status>
          <el-tag :type="statusType" size="small" :title="testResult?.message || undefined">
            {{ statusLabel }}
          </el-tag>
        </template>
        <template #actions>
          <el-button plain @click="$emit('open-converter')">
            <el-icon><Headset /></el-icon>
            {{ t('settings.svc.openConverter') }}
          </el-button>
          <el-button
            plain
            :loading="testLoading"
            :disabled="modelValue.provider === 'disabled' || !modelValue.base_url.trim() || Boolean(endpointError)"
            @click="$emit('test-service')"
          >
            <el-icon><Connection /></el-icon>
            {{ t('settings.svc.testService') }}
          </el-button>
          <el-button data-testid="discover-svc" plain :loading="discoveryLoading" @click="$emit('discover-local')">
            <el-icon><Connection /></el-icon>
            {{ t('settings.discovery.detectLocal') }}
          </el-button>
          <el-button
            text
            circle
            :aria-label="t('settings.svc.reset')"
            :title="t('settings.svc.reset')"
            @click="$emit('reset')"
          >
            <el-icon><RefreshLeft /></el-icon>
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
          <el-option :label="t('settings.svc.providerSoulx')" value="soulx-service" />
          <el-option :label="t('common.disabled')" value="disabled" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('settings.svc.baseUrl')" :error="endpointError || undefined">
        <el-input
          :model-value="modelValue.base_url"
          :disabled="modelValue.provider === 'disabled'"
          clearable
          autocomplete="url"
          placeholder="http://127.0.0.1:7861"
          @clear="emitField('base_url', '')"
          @change="emitField('base_url', $event)"
        />
      </el-form-item>
      <div class="form-grid">
        <el-form-item :label="t('settings.svc.referenceAudioId')">
          <el-input-number :model-value="modelValue.speaker_id" :min="0" :disabled="modelValue.provider === 'disabled'" controls-position="right" @change="emitField('speaker_id', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.svc.pitch')">
          <el-input-number :model-value="modelValue.pitch" :min="-36" :max="36" :disabled="modelValue.provider === 'disabled'" controls-position="right" @change="emitField('pitch', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.svc.timeout')">
          <el-input-number :model-value="modelValue.timeout" :min="10" :max="900" :disabled="modelValue.provider === 'disabled'" controls-position="right" @change="emitField('timeout', $event)" />
        </el-form-item>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElAlert, ElIcon, ElTag } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/tag/style/css'
import { ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { computed } from 'vue'
import { Connection, Headset, RefreshLeft } from '@element-plus/icons-vue'

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
  testLoading: boolean
  testResult?: {
    ok: boolean
    message?: string
  } | null
}>()

const emit = defineEmits<{
  'update-field': [field: keyof SvcSettings, value: string | number]
  'discover-local': []
  'open-converter': []
  'test-service': []
  reset: []
}>()

const hasEndpoint = computed(() => props.modelValue.provider !== 'disabled' && Boolean(props.modelValue.base_url.trim()))
const endpointError = computed(() => {
  if (props.modelValue.provider === 'disabled' || !props.modelValue.base_url.trim()) return ''
  const value = props.modelValue.base_url.trim()
  try {
    const parsed = new URL(value.includes('://') ? value : `http://${value}`)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
      ? ''
      : t('settings.svc.invalidBaseUrl')
  } catch {
    return t('settings.svc.invalidBaseUrl')
  }
})
const statusLabel = computed(() => {
  if (props.modelValue.provider === 'disabled') return t('svcPanel.svcDisabled')
  if (endpointError.value) return t('settings.svc.invalidBaseUrl')
  if (props.testLoading) return t('svcPanel.checkingService')
  if (props.testResult) return props.testResult.ok ? t('svcPanel.serviceReachable') : t('svcPanel.serviceUnavailable')
  return hasEndpoint.value ? t('settings.svc.notTested') : t('svcPanel.endpointMissing')
})
const statusType = computed(() => {
  if (props.modelValue.provider === 'disabled') return 'info'
  if (props.testLoading) return 'warning'
  if (props.testResult) return props.testResult.ok ? 'success' : 'danger'
  return hasEndpoint.value && !endpointError.value ? 'info' : 'warning'
})

const emitField = (field: keyof SvcSettings, value: unknown) => {
  if (typeof value === 'string' || typeof value === 'number') {
    if (field === 'base_url' && typeof value === 'string') {
      const trimmed = value.trim()
      emit('update-field', field, trimmed && !trimmed.includes('://') ? `http://${trimmed}` : trimmed)
      return
    }
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

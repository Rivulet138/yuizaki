<template>
  <section class="vision-section">
    <div class="subsection-title">{{ t('settingsSection.vision.title') }}</div>
    <el-form-item :label="t('settingsSection.vision.useIndependent')">
      <el-switch :model-value="modelValue.enabled" @change="update('enabled', Boolean($event))" />
    </el-form-item>
    <div v-if="modelValue.enabled" class="form-grid three">
      <el-form-item :label="t('settingsSection.vision.provider')">
        <el-select :model-value="modelValue.provider" class="full-width" @change="update('provider', String($event) as LlmProviderPreset)">
          <el-option v-for="option in providerOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('settingsSection.vision.model')">
        <el-input :model-value="modelValue.model" @update:model-value="update('model', String($event))" />
      </el-form-item>
      <el-form-item :label="t('settingsSection.vision.timeout')">
        <el-input-number :model-value="modelValue.timeout" :min="5" :max="120" controls-position="right" @change="updateTimeout" />
      </el-form-item>
      <el-form-item :label="t('settingsSection.vision.detail')">
        <el-select :model-value="modelValue.detail" class="full-width" @change="update('detail', String($event) as VisionDetail)">
          <el-option :label="t('settingsSection.vision.detailLow')" value="low" />
          <el-option :label="t('settingsSection.vision.detailAuto')" value="auto" />
          <el-option :label="t('settingsSection.vision.detailHigh')" value="high" />
          <el-option :label="t('settingsSection.vision.detailOriginal')" value="original" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('settingsSection.vision.baseUrl')">
        <el-input :model-value="modelValue.baseUrl" @update:model-value="update('baseUrl', String($event))" />
      </el-form-item>
      <el-form-item v-if="!keylessProviders.has(modelValue.provider)" :label="t('settingsSection.vision.apiKey')">
        <el-input :model-value="modelValue.apiKey" type="password" show-password @update:model-value="update('apiKey', String($event))" />
      </el-form-item>
    </div>
    <p v-if="modelValue.enabled && (!modelValue.baseUrl.trim() || !modelValue.model.trim())" class="field-hint error">
      {{ t('settingsSection.vision.missingConfig') }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { ElSwitch } from 'element-plus'
import 'element-plus/es/components/switch/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElFormItem } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { t } from '@/i18n'
import type { LlmProviderPreset } from '../llmProviders'

type VisionDetail = 'low' | 'high' | 'auto' | 'original'

interface LlmVisionSettings {
  enabled: boolean
  provider: LlmProviderPreset
  baseUrl: string
  apiKey: string
  model: string
  timeout: number
  detail: VisionDetail
}

defineProps<{
  modelValue: LlmVisionSettings
  providerOptions: Array<{ label: string; value: LlmProviderPreset }>
}>()

const emit = defineEmits<{
  update: [patch: Partial<LlmVisionSettings>]
}>()

const keylessProviders = new Set<LlmProviderPreset>(['ollama', 'lmstudio'])
const update = <Key extends keyof LlmVisionSettings>(key: Key, value: LlmVisionSettings[Key]) => {
  emit('update', { [key]: value })
}
const updateTimeout = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return
  update('timeout', Math.min(120, Math.max(5, value)))
}
</script>

<style scoped src="./SettingsLlmVisionSection.css"></style>

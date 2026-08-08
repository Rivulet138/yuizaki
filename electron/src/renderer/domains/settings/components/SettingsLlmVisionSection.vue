<template>
  <section class="vision-section">
    <div class="subsection-title">实时视觉模型</div>
    <el-form-item label="使用独立视觉模型">
      <el-switch :model-value="modelValue.enabled" @change="update('enabled', Boolean($event))" />
    </el-form-item>
    <div v-if="modelValue.enabled" class="form-grid three">
      <el-form-item label="视觉提供商">
        <el-select :model-value="modelValue.provider" class="full-width" @change="update('provider', String($event) as LlmProviderPreset)">
          <el-option v-for="option in providerOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="视觉模型">
        <el-input :model-value="modelValue.model" @update:model-value="update('model', String($event))" />
      </el-form-item>
      <el-form-item label="视觉超时">
        <el-input-number :model-value="modelValue.timeout" :min="5" :max="120" controls-position="right" @change="updateTimeout" />
      </el-form-item>
      <el-form-item label="Vision detail">
        <el-select :model-value="modelValue.detail" class="full-width" @change="update('detail', String($event) as VisionDetail)">
          <el-option label="Low latency" value="low" />
          <el-option label="Auto" value="auto" />
          <el-option label="High fidelity" value="high" />
          <el-option label="Original" value="original" />
        </el-select>
      </el-form-item>
      <el-form-item label="视觉 API 地址（OpenAI 兼容）">
        <el-input :model-value="modelValue.baseUrl" @update:model-value="update('baseUrl', String($event))" />
      </el-form-item>
      <el-form-item v-if="!keylessProviders.has(modelValue.provider)" label="视觉 API Key">
        <el-input :model-value="modelValue.apiKey" type="password" show-password @update:model-value="update('apiKey', String($event))" />
      </el-form-item>
    </div>
    <p v-if="modelValue.enabled && (!modelValue.baseUrl.trim() || !modelValue.model.trim())" class="field-hint error">
      视觉 API 地址和视觉模型未配置
    </p>
  </section>
</template>

<script setup lang="ts">
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

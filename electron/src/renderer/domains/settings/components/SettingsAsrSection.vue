<template>
  <el-card shadow="never">
    <template #header>
      <SettingsSectionHeader :title="t('settings.asr.title')">
        <template #status>
          <el-tag :type="statusType" size="small">{{ statusLabel }}</el-tag>
        </template>
        <template #actions>
          <el-button plain :loading="discoveryLoading" @click="$emit('discover-local')">
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
      <div class="form-grid">
        <el-form-item :label="t('settings.asr.provider')">
          <el-select :model-value="modelValue.provider" class="full-width" @change="emitField('provider', $event)">
            <el-option label="SenseVoice Service" value="sensevoice-service" />
            <el-option label="FunASR Service" value="funasr-service" />
            <el-option label="OpenAI Compatible" value="openai-compatible" />
            <el-option label="Sherpa ONNX" value="sherpa-onnx" />
            <el-option label="Sherpa ONNX Streaming" value="sherpa-onnx-online" />
            <el-option label="SenseVoice Local" value="sensevoice-local" />
            <el-option :label="t('common.disabled')" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="usesService" :label="t('settings.asr.baseUrl')">
          <el-input :model-value="modelValue.base_url" @change="emitField('base_url', $event)" />
        </el-form-item>
        <el-form-item v-if="modelValue.provider === 'openai-compatible'" :label="t('settings.asr.apiKey')">
          <el-input :model-value="modelValue.api_key" type="password" show-password @change="emitField('api_key', $event)" />
        </el-form-item>
      </div>

      <div v-if="usesService || usesLocalSenseVoice" class="form-grid three">
        <el-form-item :label="t('settings.asr.sensevoiceModel')">
          <el-input :model-value="modelValue.sensevoice_model" placeholder="iic/SenseVoiceSmall" @change="emitField('sensevoice_model', $event)" />
        </el-form-item>
        <el-form-item v-if="usesLocalSenseVoice" :label="t('settings.asr.sensevoiceDevice')">
          <el-select :model-value="modelValue.sensevoice_device" class="full-width" @change="emitField('sensevoice_device', $event)">
            <el-option label="CPU" value="cpu" />
            <el-option label="CUDA" value="cuda" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="usesService" :label="t('settings.asr.timeout')">
          <el-input-number :model-value="modelValue.timeout" :min="5" :max="300" controls-position="right" @change="emitField('timeout', $event)" />
        </el-form-item>
      </div>

      <div v-if="usesSherpa" class="form-grid two">
        <el-form-item :label="t('settings.asr.sherpaModel')">
          <el-input
            :model-value="modelValue.sherpa_model_path"
            :placeholder="modelValue.provider === 'sherpa-onnx-online'
              ? './.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh/model.int8.onnx'
              : './.cache/sherpa-onnx/sensevoice/model.int8.onnx'"
            @change="emitField('sherpa_model_path', $event)"
          />
        </el-form-item>
        <el-form-item :label="t('settings.asr.sherpaTokens')">
          <el-input
            :model-value="modelValue.sherpa_tokens_path"
            :placeholder="modelValue.provider === 'sherpa-onnx-online'
              ? './.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh/tokens.txt'
              : './.cache/sherpa-onnx/sensevoice/tokens.txt'"
            @change="emitField('sherpa_tokens_path', $event)"
          />
        </el-form-item>
        <el-form-item :label="t('settings.asr.sherpaThreads')">
          <el-input-number :model-value="modelValue.sherpa_num_threads" :min="1" :max="16" controls-position="right" @change="emitField('sherpa_num_threads', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.asr.sherpaProvider')">
          <el-select :model-value="modelValue.sherpa_provider" class="full-width" @change="emitField('sherpa_provider', $event)">
            <el-option label="CPU" value="cpu" />
            <el-option label="CUDA" value="cuda" />
            <el-option label="Core ML" value="coreml" />
          </el-select>
        </el-form-item>
      </div>

      <div v-if="enabled" class="form-grid two">
        <el-form-item :label="t('settings.asr.languageHint')">
          <el-input :model-value="modelValue.language" placeholder="zh" @change="emitField('language', $event)" />
        </el-form-item>
        <el-form-item v-if="modelValue.provider !== 'sherpa-onnx-online'" :label="t('settings.asr.partialInterval')">
          <el-input-number :model-value="modelValue.asr_partial_every" :min="1" :max="30" controls-position="right" @change="emitField('asr_partial_every', $event)" />
        </el-form-item>
      </div>

      <div v-if="enabled" class="form-grid">
        <el-form-item :label="t('settings.asr.vadThreshold', { value: modelValue.vad_threshold.toFixed(2) })">
          <el-slider :model-value="modelValue.vad_threshold" :min="0.1" :max="0.9" :step="0.1" @change="emitField('vad_threshold', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.asr.endpointSilenceCap', { value: modelValue.vad_min_silence_ms })">
          <el-slider :model-value="modelValue.vad_min_silence_ms" :min="160" :max="1200" :step="32" @change="emitField('vad_min_silence_ms', $event)" />
        </el-form-item>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { Connection } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { t } from '@/i18n'
import SettingsSectionHeader from './SettingsSectionHeader.vue'

export type AsrSettings = {
  provider: string
  base_url: string
  api_key: string
  timeout: number
  sensevoice_model: string
  sensevoice_device: string
  sherpa_model_path: string
  sherpa_tokens_path: string
  sherpa_num_threads: number
  sherpa_provider: string
  language: string
  vad_threshold: number
  vad_min_silence_ms: number
  asr_partial_every: number
}

const props = defineProps<{
  modelValue: AsrSettings
  discoveryLoading: boolean
  discoveryError?: string | null
}>()

const emit = defineEmits<{
  'update-field': [field: keyof AsrSettings, value: string | number]
  'discover-local': []
}>()

const usesService = computed(() => ['sensevoice-service', 'funasr-service', 'openai-compatible'].includes(props.modelValue.provider))
const usesLocalSenseVoice = computed(() => props.modelValue.provider === 'sensevoice-local')
const usesSherpa = computed(() => props.modelValue.provider === 'sherpa-onnx' || props.modelValue.provider === 'sherpa-onnx-online')
const enabled = computed(() => props.modelValue.provider !== 'disabled')
const statusLabel = computed(() => enabled.value ? props.modelValue.provider : t('common.disabled'))
const statusType = computed(() => enabled.value ? 'success' : 'info')

const emitField = (field: keyof AsrSettings, value: unknown) => {
  if (typeof value === 'string' || typeof value === 'number') {
    emit('update-field', field, value)
  }
}
</script>

<style scoped>
.discovery-error {
  margin-bottom: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.full-width {
  width: 100%;
}

@media (max-width: 900px) {
  .form-grid,
  .form-grid.three {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

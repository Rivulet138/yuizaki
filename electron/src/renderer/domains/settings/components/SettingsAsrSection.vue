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

    <section class="asr-guide" :aria-label="t('settings.asr.guide.title')">
      <div class="asr-guide-title-row">
        <span class="asr-guide-provider">{{ providerGuide.title }}</span>
      </div>
      <div v-if="providerGuide.links.length" class="asr-guide-line">
        <span class="asr-guide-label">{{ t('settings.asr.guide.download') }}</span>
        <span class="asr-guide-links">
          <a
            v-for="link in providerGuide.links"
            :key="link.href"
            :href="link.href"
            target="_blank"
            rel="noreferrer"
          >
            {{ link.label }}
          </a>
        </span>
      </div>

      <div v-if="providerGuide.placement" class="asr-guide-line">
        <span class="asr-guide-label">{{ t('settings.asr.guide.placement') }}</span>
        <code>{{ providerGuide.placement }}</code>
      </div>

      <template v-if="usesService">
        <div class="asr-guide-line">
          <span class="asr-guide-label">{{ t('settings.asr.guide.serviceEntry') }}</span>
          <code>{{ providerGuide.baseUrl }}</code>
        </div>
        <div class="asr-guide-line">
          <span class="asr-guide-label">{{ t('settings.asr.guide.serviceDocs') }}</span>
          <span class="asr-guide-links">
            <a
              v-for="link in providerGuide.serviceLinks"
              :key="link.href"
              :href="link.href"
              target="_blank"
              rel="noreferrer"
            >
              {{ link.label }}
            </a>
          </span>
        </div>
      </template>
    </section>

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
          <el-option label="Sherpa Streaming + SenseVoice" value="sherpa-onnx-online" />
          <el-option label="SenseVoice Local" value="sensevoice-local" />
            <el-option :label="t('common.disabled')" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="usesService" :label="t('settings.asr.baseUrl')">
          <el-input :model-value="modelValue.base_url" :placeholder="providerGuide.baseUrl" @change="emitField('base_url', $event)" />
        </el-form-item>
        <el-form-item v-if="usesService" :label="t('settings.asr.apiKey')">
          <el-input :model-value="modelValue.api_key" type="password" show-password @change="emitField('api_key', $event)" />
        </el-form-item>
      </div>

      <div v-if="usesService || usesLocalSenseVoice" class="form-grid three">
        <el-form-item :label="usesService ? t('settings.asr.serviceModel') : t('settings.asr.sensevoiceModel')">
          <el-input :model-value="modelValue.sensevoice_model" :placeholder="providerGuide.model" @change="emitField('sensevoice_model', $event)" />
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
import { ElAlert, ElIcon } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/icon/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSlider } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { Connection } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { currentLocale, t } from '@/i18n'
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

type GuideLink = { label: string; href: string }
type ProviderGuide = {
  title: string
  description: string
  placement: string
  model: string
  baseUrl: string
  links: GuideLink[]
  serviceLinks: GuideLink[]
}

const providerGuide = computed<ProviderGuide>(() => {
  void currentLocale.value
  if (props.modelValue.provider === 'sherpa-onnx') {
    return {
      title: 'Sherpa ONNX',
      description: t('settings.asr.guide.sherpa.description'),
      placement: 'python/.cache/sherpa-onnx/sensevoice/',
      model: 'iic/SenseVoiceSmall',
      baseUrl: '',
      links: [
        { label: t('settings.asr.guide.sherpa.download'), href: 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2' },
        { label: t('settings.asr.guide.sherpa.modelPage'), href: 'https://huggingface.co/FunAudioLLM/SenseVoiceSmall' },
      ],
      serviceLinks: [],
    }
  }
  if (props.modelValue.provider === 'sherpa-onnx-online') {
    return {
      title: 'Sherpa Streaming + SenseVoice',
      description: t('settings.asr.guide.sherpaOnline.description'),
      placement: 'python/.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh/',
      model: 'iic/SenseVoiceSmall',
      baseUrl: '',
      links: [
        { label: t('settings.asr.guide.sherpaOnline.download'), href: 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01.tar.bz2' },
        { label: t('settings.asr.guide.sherpaOnline.modelPage'), href: 'https://github.com/k2-fsa/sherpa-onnx' },
      ],
      serviceLinks: [],
    }
  }
  if (props.modelValue.provider === 'sensevoice-local') {
    return {
      title: 'SenseVoice Local',
      description: t('settings.asr.guide.sensevoiceLocal.description'),
      placement: t('settings.asr.guide.sensevoiceLocal.placement'),
      model: 'iic/SenseVoiceSmall',
      baseUrl: '',
      links: [
        { label: t('settings.asr.guide.sensevoiceLocal.modelScope'), href: 'https://www.modelscope.cn/models/iic/SenseVoiceSmall' },
        { label: t('settings.asr.guide.sensevoiceLocal.huggingFace'), href: 'https://huggingface.co/FunAudioLLM/SenseVoiceSmall' },
      ],
      serviceLinks: [],
    }
  }
  if (props.modelValue.provider === 'sensevoice-service') {
    return {
      title: 'SenseVoice Service',
      description: t('settings.asr.guide.sensevoiceService.description'),
      placement: '',
      model: 'iic/SenseVoiceSmall',
      baseUrl: 'http://127.0.0.1:8899/v1',
      links: [],
      serviceLinks: [
        { label: t('settings.asr.guide.service.funASRDocs'), href: 'https://github.com/modelscope/FunASR/tree/main/runtime/docs' },
      ],
    }
  }
  if (props.modelValue.provider === 'funasr-service') {
    return {
      title: 'FunASR Service',
      description: t('settings.asr.guide.funasrService.description'),
      placement: '',
      model: 'iic/SenseVoiceSmall',
      baseUrl: 'http://127.0.0.1:8899/v1',
      links: [],
      serviceLinks: [
        { label: t('settings.asr.guide.service.funASRDocs'), href: 'https://github.com/modelscope/FunASR/tree/main/runtime/docs' },
      ],
    }
  }
  if (props.modelValue.provider === 'openai-compatible') {
    return {
      title: 'OpenAI Compatible',
      description: t('settings.asr.guide.openaiCompatible.description'),
      placement: '',
      model: t('settings.asr.guide.openaiCompatible.model'),
      baseUrl: 'https://api.openai.com/v1',
      links: [],
      serviceLinks: [
        { label: t('settings.asr.guide.service.openAIDocs'), href: 'https://platform.openai.com/docs/api-reference/audio/createTranscription' },
      ],
    }
  }
  return {
    title: t('common.disabled'),
    description: t('settings.asr.guide.disabled.description'),
    placement: '',
    model: 'iic/SenseVoiceSmall',
    baseUrl: '',
    links: [],
    serviceLinks: [],
  }
})

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

.asr-action-note {
  margin: 0 0 14px;
  padding: 8px 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  color: var(--yui-muted);
  background: var(--yui-surface-muted);
  font-size: 12px;
  line-height: 1.5;
}

.asr-guide {
  margin: 0 0 16px;
  padding: 10px 12px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.asr-guide-title-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px 10px;
  color: var(--yui-text);
}

.asr-guide-provider {
  color: var(--yui-muted);
  font-weight: 400;
}

.asr-guide-copy {
  max-width: 76ch;
  margin: 3px 0 8px;
}

.asr-guide-copy-tight {
  margin: 6px 0;
}

.asr-guide-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin-top: 5px;
}

.asr-guide-label {
  color: var(--yui-text);
  font-weight: 600;
}

.asr-guide code {
  max-width: 100%;
  overflow-wrap: anywhere;
  color: var(--yui-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.asr-guide-links {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.asr-guide-links a {
  color: var(--yui-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.asr-guide-links a:hover {
  color: var(--yui-accent-strong, var(--yui-accent));
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

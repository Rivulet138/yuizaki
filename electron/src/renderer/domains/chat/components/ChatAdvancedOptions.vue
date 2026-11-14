<template>
  <el-popover placement="top" width="320" trigger="click">
    <template #reference>
      <button class="tool-button" type="button" :aria-label="t('chatPanel.advanced.openAria')">
        <el-icon><Timer /></el-icon>
      </button>
    </template>
    <div class="advanced-options">
      <label v-if="capabilities.parameters.temperature">
        <span>{{ t('chatPanel.advanced.temperature', { value: modelValue.temperature?.toFixed(2) }) }}</span>
        <el-slider v-if="capabilities.parameters.temperature!.min < capabilities.parameters.temperature!.max" :model-value="modelValue.temperature" :min="capabilities.parameters.temperature!.min" :max="capabilities.parameters.temperature!.max" :step="0.05" @update:model-value="emitField('temperature', $event)" />
      </label>
      <label v-if="capabilities.parameters.top_p">
        <span>Top P {{ modelValue.top_p?.toFixed(2) }}</span>
        <el-slider v-if="capabilities.parameters.top_p!.min < capabilities.parameters.top_p!.max" :model-value="modelValue.top_p" :min="capabilities.parameters.top_p!.min" :max="capabilities.parameters.top_p!.max" :step="0.05" @update:model-value="emitField('top_p', $event)" />
      </label>
      <div v-if="capabilities.parameters.top_k || capabilities.parameters.min_p" class="advanced-options-grid">
        <label v-if="capabilities.parameters.top_k">
          <span>Top K</span>
          <el-input-number :model-value="modelValue.top_k" :min="0" :max="capabilities.parameters.top_k!.max" :step="1" size="small" @update:model-value="emitField('top_k', $event)" />
        </label>
        <label v-if="capabilities.parameters.min_p">
          <span>Min P {{ modelValue.min_p?.toFixed(2) }}</span>
          <el-slider v-if="capabilities.parameters.min_p!.min < capabilities.parameters.min_p!.max" :model-value="modelValue.min_p" :min="capabilities.parameters.min_p!.min" :max="capabilities.parameters.min_p!.max" :step="0.01" @update:model-value="emitField('min_p', $event)" />
        </label>
      </div>
      <div v-if="capabilities.parameters.frequency_penalty || capabilities.parameters.presence_penalty" class="advanced-options-grid">
        <label v-if="capabilities.parameters.frequency_penalty">
          <span>{{ t('chatPanel.advanced.frequencyPenalty', { value: modelValue.frequency_penalty?.toFixed(2) }) }}</span>
          <el-slider v-if="capabilities.parameters.frequency_penalty!.min < capabilities.parameters.frequency_penalty!.max" :model-value="modelValue.frequency_penalty" :min="capabilities.parameters.frequency_penalty!.min" :max="capabilities.parameters.frequency_penalty!.max" :step="0.05" @update:model-value="emitField('frequency_penalty', $event)" />
        </label>
        <label v-if="capabilities.parameters.presence_penalty">
          <span>{{ t('chatPanel.advanced.presencePenalty', { value: modelValue.presence_penalty?.toFixed(2) }) }}</span>
          <el-slider v-if="capabilities.parameters.presence_penalty!.min < capabilities.parameters.presence_penalty!.max" :model-value="modelValue.presence_penalty" :min="capabilities.parameters.presence_penalty!.min" :max="capabilities.parameters.presence_penalty!.max" :step="0.05" @update:model-value="emitField('presence_penalty', $event)" />
        </label>
      </div>
      <label v-if="capabilities.parameters.repetition_penalty">
        <span>{{ t('chatPanel.advanced.repetitionPenalty', { value: modelValue.repetition_penalty?.toFixed(2) }) }}</span>
        <el-slider v-if="capabilities.parameters.repetition_penalty!.min < capabilities.parameters.repetition_penalty!.max" :model-value="modelValue.repetition_penalty" :min="capabilities.parameters.repetition_penalty!.min" :max="capabilities.parameters.repetition_penalty!.max" :step="0.05" @update:model-value="emitField('repetition_penalty', $event)" />
      </label>
      <label>
        <span>{{ t('chatPanel.advanced.maxReplyLength') }}</span>
        <el-input-number :model-value="modelValue.max_tokens" :min="128" :max="maxOutputTokens" :step="128" size="small" @update:model-value="emitField('max_tokens', $event)" />
      </label>
      <label>
        <span>{{ t('chatPanel.advanced.translationTarget') }}</span>
        <el-select :model-value="modelValue.translation_target" size="small" filterable @update:model-value="emitField('translation_target', $event)">
          <el-option :label="t('chatPanel.advanced.langZh')" value="zh-CN" />
          <el-option label="English" value="en" />
          <el-option :label="t('chatPanel.advanced.langJa')" value="ja" />
          <el-option label="한국어" value="ko" />
          <el-option label="Français" value="fr" />
          <el-option label="Deutsch" value="de" />
        </el-select>
      </label>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ElIcon, ElPopover } from 'element-plus'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/popover/style/css'
import { ElSlider } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { Timer } from '@element-plus/icons-vue'
import { t } from '@/i18n'
import type { GenerationCapabilities } from '@/../shared/llm-generation-parameters'

export type ChatAdvancedOptionsModel = {
  temperature: number
  top_p: number
  top_k: number
  min_p: number
  frequency_penalty: number
  presence_penalty: number
  repetition_penalty: number
  max_tokens: number
  translation_target: string
}

defineProps<{
  modelValue: ChatAdvancedOptionsModel
  capabilities: GenerationCapabilities
  maxOutputTokens: number
}>()

const emit = defineEmits<{
  'update-field': [field: keyof ChatAdvancedOptionsModel, value: number | string]
}>()

const emitField = (field: keyof ChatAdvancedOptionsModel, value: unknown) => {
  if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) {
    emit('update-field', field, value)
  }
}
</script>

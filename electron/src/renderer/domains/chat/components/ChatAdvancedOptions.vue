<template>
  <el-popover placement="top" width="320" trigger="click">
    <template #reference>
      <button class="tool-button" type="button" :aria-label="t('chatPanel.advanced.openAria')">
        <el-icon><Timer /></el-icon>
      </button>
    </template>
    <div class="advanced-options">
      <label>
        <span>{{ t('chatPanel.advanced.temperature', { value: modelValue.temperature?.toFixed(2) }) }}</span>
        <el-slider :model-value="modelValue.temperature" :min="0" :max="2" :step="0.05" @update:model-value="emitField('temperature', $event)" />
      </label>
      <label>
        <span>Top P {{ modelValue.top_p?.toFixed(2) }}</span>
        <el-slider :model-value="modelValue.top_p" :min="0" :max="1" :step="0.05" @update:model-value="emitField('top_p', $event)" />
      </label>
      <div class="advanced-options-grid">
        <label>
          <span>Top K</span>
          <el-input-number :model-value="modelValue.top_k" :min="0" :max="2000" :step="50" size="small" @update:model-value="emitField('top_k', $event)" />
        </label>
        <label>
          <span>Min P {{ modelValue.min_p?.toFixed(2) }}</span>
          <el-slider :model-value="modelValue.min_p" :min="0" :max="1" :step="0.01" @update:model-value="emitField('min_p', $event)" />
        </label>
      </div>
      <div class="advanced-options-grid">
        <label>
          <span>{{ t('chatPanel.advanced.frequencyPenalty', { value: modelValue.frequency_penalty?.toFixed(2) }) }}</span>
          <el-slider :model-value="modelValue.frequency_penalty" :min="-2" :max="2" :step="0.05" @update:model-value="emitField('frequency_penalty', $event)" />
        </label>
        <label>
          <span>{{ t('chatPanel.advanced.presencePenalty', { value: modelValue.presence_penalty?.toFixed(2) }) }}</span>
          <el-slider :model-value="modelValue.presence_penalty" :min="-2" :max="2" :step="0.05" @update:model-value="emitField('presence_penalty', $event)" />
        </label>
      </div>
      <label>
        <span>{{ t('chatPanel.advanced.repetitionPenalty', { value: modelValue.repetition_penalty?.toFixed(2) }) }}</span>
        <el-slider :model-value="modelValue.repetition_penalty" :min="0" :max="2" :step="0.05" @update:model-value="emitField('repetition_penalty', $event)" />
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

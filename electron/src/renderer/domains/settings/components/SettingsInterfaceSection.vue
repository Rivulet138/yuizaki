<template>
  <el-card shadow="never">
    <template #header>{{ t('settings.interface.title') }}</template>
    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="t('settings.system.theme')">
        <el-segmented
          data-testid="theme-selector"
          :model-value="modelValue.theme"
          :options="themeOptions"
          @change="$emit('change-theme', String($event))"
        />
      </el-form-item>
      <el-form-item :label="t('settings.system.language')">
        <el-segmented
          data-testid="language-selector"
          :model-value="modelValue.language"
          :options="languageOptions"
          @change="$emit('change-language', String($event))"
        />
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { ElSegmented } from 'element-plus'
import 'element-plus/es/components/segmented/style/css'
import { ElCard, ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { t } from '@/i18n'

export type InterfaceSettings = {
  theme: string
  language: string
}

export type InterfaceOption = {
  label: string
  value: string
}

defineProps<{
  modelValue: InterfaceSettings
  themeOptions: InterfaceOption[]
  languageOptions: InterfaceOption[]
}>()

defineEmits<{
  'change-theme': [value: string]
  'change-language': [value: string]
}>()
</script>

<template>
  <el-popover placement="top-end" :width="380" trigger="click" popper-class="chat-runtime-popper" @show="emit('refresh-audio-devices')">
    <template #reference>
      <button class="runtime-settings-button" type="button" :aria-label="t('chatPanel.runtime.openAria')" :title="t('chatPanel.runtime.openAria')">
        <el-icon><Operation /></el-icon>
      </button>
    </template>

    <div class="runtime-settings">
      <header class="runtime-settings__header">
        <strong>{{ t('chatPanel.runtime.title') }}</strong>
        <span :title="modelLabel">{{ modelLabel }}</span>
      </header>

      <el-segmented
        :model-value="modelValue.response_mode"
        :options="responseModeOptions"
        size="small"
        class="runtime-settings__modes"
        :aria-label="t('chatPanel.runtime.responseSpeedAria')"
        @update:model-value="emitField('response_mode', $event)"
      />

      <label class="runtime-field">
        <span>{{ t('chatPanel.runtime.voice') }}</span>
        <el-segmented
          :model-value="modelValue.voice_mode"
          :options="voiceModeOptions"
          size="small"
          @update:model-value="emitField('voice_mode', $event)"
        />
      </label>

      <label class="runtime-field">
        <span>{{ t('chatPanel.runtime.vadEagerness') }}</span>
        <el-segmented
          :model-value="modelValue.vad_eagerness"
          :options="vadEagernessOptions"
          size="small"
          @update:model-value="emitField('vad_eagerness', $event)"
        />
      </label>

      <label class="runtime-field">
        <span>{{ t('chatPanel.runtime.microphone') }}</span>
        <el-select
          :model-value="modelValue.audio_input_device_id"
          size="small"
          clearable
          :loading="audioDevicesLoading"
          :placeholder="t('chatPanel.runtime.systemDefault')"
          @update:model-value="emitField('audio_input_device_id', $event)"
        >
          <el-option :label="t('chatPanel.runtime.systemDefault')" value="" />
          <el-option v-for="device in audioInputDevices" :key="device.deviceId" :label="device.label" :value="device.deviceId" />
        </el-select>
      </label>

      <label class="runtime-field">
        <span>{{ t('chatPanel.runtime.model') }}</span>
        <el-select
          :model-value="modelValue.model"
          size="small"
          clearable
          filterable
          :placeholder="t('chatPanel.runtime.defaultModel')"
          :loading="modelsLoading"
          @visible-change="(visible: boolean) => visible && emit('refresh-models')"
          @update:model-value="emitField('model', $event)"
        >
          <el-option :label="t('chatPanel.runtime.defaultModel')" value="" />
          <el-option v-for="model in modelOptions" :key="model" :label="model" :value="model" />
        </el-select>
      </label>

      <label class="runtime-field">
        <span>{{ t('chatPanel.runtime.reasoning') }}</span>
        <el-select
          :model-value="modelValue.reasoning_effort"
          size="small"
          @update:model-value="emitField('reasoning_effort', $event)"
        >
          <el-option v-for="item in reasoningOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </label>

      <div class="runtime-toggles">
        <label>
          <span>{{ t('chatPanel.runtime.mcpTools') }}</span>
          <el-switch :model-value="modelValue.mcp_enabled" @update:model-value="emitField('mcp_enabled', $event)" />
        </label>
        <label>
          <span>{{ t('chatPanel.runtime.petLink') }}</span>
          <el-switch :model-value="modelValue.pet_link_enabled" @update:model-value="emitField('pet_link_enabled', $event)" />
        </label>
        <label>
          <span>{{ t('chatPanel.runtime.voiceReply') }}</span>
          <el-switch :model-value="modelValue.tts_enabled" @update:model-value="emitTts" />
        </label>
      </div>

      <footer class="runtime-settings__footer">
        <button class="runtime-link-button" :class="{ active: promptActive }" type="button" @click="emit('open-prompt')">
          <el-icon><Tickets /></el-icon>
          <span>{{ t('chatPanel.runtime.prompt') }}</span>
        </button>
        <ChatAdvancedOptions
          :model-value="modelValue"
          :max-output-tokens="maxOutputTokens"
          @update-field="(field, value) => emit('update-field', field, value)"
        />
      </footer>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ElIcon, ElPopover } from 'element-plus'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/popover/style/css'
import { ElSegmented, ElSwitch } from 'element-plus'
import 'element-plus/es/components/segmented/style/css'
import 'element-plus/es/components/switch/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { Operation, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'
import ChatAdvancedOptions, { type ChatAdvancedOptionsModel } from './ChatAdvancedOptions.vue'
import { t } from '@/i18n'

export type ChatRuntimeSettingsModel = ChatAdvancedOptionsModel & {
  model: string
  response_mode: string
  voice_mode: 'push-to-talk' | 'continuous'
  vad_eagerness: 'low' | 'medium' | 'high' | 'auto'
  audio_input_device_id: string
  reasoning_effort: string
  mcp_enabled: boolean
  pet_link_enabled: boolean
  tts_enabled: boolean
}

type SelectOption = { label: string; value: string }
export type AudioInputDeviceOption = { deviceId: string; label: string }

const voiceModeOptions = computed(() => [
  { label: t('chatPanel.runtime.voiceModeKey'), value: 'push-to-talk' },
  { label: t('chatPanel.runtime.voiceModeContinuous'), value: 'continuous' },
])

const vadEagernessOptions = computed(() => [
  { label: t('chatPanel.runtime.vadLow'), value: 'low' },
  { label: t('chatPanel.runtime.vadMedium'), value: 'medium' },
  { label: t('chatPanel.runtime.vadHigh'), value: 'high' },
  { label: t('chatPanel.runtime.vadAuto'), value: 'auto' },
])

defineProps<{
  modelValue: ChatRuntimeSettingsModel
  modelOptions: string[]
  modelsLoading?: boolean
  reasoningOptions: SelectOption[]
  responseModeOptions: SelectOption[]
  maxOutputTokens: number
  modelLabel: string
  promptActive: boolean
  audioInputDevices: AudioInputDeviceOption[]
  audioDevicesLoading?: boolean
}>()

const emit = defineEmits<{
  'update-field': [field: keyof ChatRuntimeSettingsModel, value: string | number | boolean]
  'toggle-tts': [enabled: boolean]
  'open-prompt': []
  'refresh-models': []
  'refresh-audio-devices': []
}>()

const emitField = (field: keyof ChatRuntimeSettingsModel, value: unknown) => {
  if (typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) {
    emit('update-field', field, value)
  }
}

const emitTts = (value: unknown) => emit('toggle-tts', value === true)
</script>

<style scoped>
.runtime-settings-button {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--yui-chat-muted, var(--yui-muted));
  cursor: pointer;
  font-size: 15px;
}

.runtime-settings-button:hover {
  background: var(--yui-chat-hover, var(--yui-surface-muted));
  color: var(--yui-chat-text, var(--yui-text));
}

.runtime-settings-button:focus-visible {
  outline: 2px solid var(--yui-chat-focus, var(--yui-accent-soft));
  outline-offset: 2px;
}

.runtime-settings {
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: var(--yui-text);
}

.runtime-settings__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--yui-border);
  padding-bottom: 10px;
}

.runtime-settings__header strong {
  font-size: 14px;
}

.runtime-settings__header span {
  max-width: 210px;
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-settings__modes {
  width: 100%;
}

.runtime-field,
.runtime-toggles label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--yui-text);
  font-size: 13px;
}

.runtime-field > span {
  flex: 0 0 56px;
  color: var(--yui-muted);
}

.runtime-field :deep(.el-select) {
  width: 100%;
}

.runtime-toggles {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  border-top: 1px solid var(--yui-border);
  border-bottom: 1px solid var(--yui-border);
  padding: 10px 0;
}

.runtime-toggles label {
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.runtime-settings__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.runtime-link-button {
  display: inline-flex;
  height: 30px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--yui-border);
  border-radius: 7px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 0 10px;
}

.runtime-link-button.active {
  border-color: color-mix(in srgb, var(--yui-accent) 32%, var(--yui-border));
  color: var(--yui-accent);
}

@media (max-width: 520px) {
  .runtime-toggles {
    grid-template-columns: 1fr;
  }

  .runtime-toggles label {
    flex-direction: row;
    align-items: center;
  }
}

@media (max-width: 900px) {
  .runtime-settings-button {
    width: 44px;
    height: 44px;
  }
}
</style>

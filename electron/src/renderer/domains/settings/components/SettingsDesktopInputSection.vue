<template>
  <el-card class="desktop-input-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div class="header-title"><span>桌面输入</span></div>
        <div class="button-row">
          <el-tag :type="state.status.pushToTalkActive ? 'success' : 'warning'">
            {{ state.status.pushToTalkActive ? '侧键监听可用' : '侧键监听不可用' }}
          </el-tag>
          <el-button
            data-testid="reset-input-bindings"
            :icon="Refresh"
            :loading="state.loading"
            title="恢复默认快捷键"
            aria-label="恢复默认快捷键"
            @click="$emit('reset')"
          />
        </div>
      </div>
    </template>

    <el-alert
      v-if="!state.available"
      type="info"
      :closable="false"
      title="桌面输入配置仅在 Electron 应用中可用"
    />
    <el-alert
      v-else-if="state.status.errors.length"
      type="warning"
      :closable="false"
      :title="state.status.errors.join('；')"
    />

    <el-form class="desktop-input-form" label-position="top" @submit.prevent>
      <div class="desktop-input-row">
        <div><strong>按住说话</strong></div>
        <el-switch
          data-testid="toggle-talk"
          :model-value="state.settings.pushToTalk.enabled"
          :disabled="!state.available || state.loading"
          @change="$emit('set-push-to-talk-enabled', Boolean($event))"
        />
        <el-select
          data-testid="mouse-button"
          :model-value="state.settings.pushToTalk.mouseButton"
          :disabled="!state.available || state.loading"
          class="desktop-input-select"
          @change="$emit('set-push-to-talk-mouse-button', Number($event))"
        >
          <el-option label="鼠标侧键 1（后退）" :value="4" />
          <el-option label="鼠标侧键 2（前进）" :value="5" />
        </el-select>
      </div>

      <div class="keyboard-binding-list">
        <div v-for="binding in keyboardBindingRows" :key="binding.action" class="keyboard-binding-row">
          <div><strong>{{ binding.label }}</strong></div>
          <el-input
            :data-testid="binding.action === 'interact' ? 'shortcut' : undefined"
            :model-value="state.settings.keyboard[binding.action]"
            :placeholder="activeKeyboardCapture === binding.action ? '请按下组合键' : '点击后按下组合键'"
            :disabled="!state.available || state.loading"
            readonly
            @focus="activeKeyboardCapture = binding.action"
            @blur="activeKeyboardCapture = null"
            @keydown.prevent="$emit('capture-keyboard', binding.action, $event)"
          >
            <template #append>
              <el-button
                :icon="CircleClose"
                :disabled="!state.settings.keyboard[binding.action]"
                :title="`禁用${binding.label}`"
                :aria-label="`禁用${binding.label}`"
                @mousedown.prevent
                @click="$emit('clear-keyboard', binding.action)"
              />
            </template>
          </el-input>
          <el-tag :type="state.status.keyboard[binding.action] ? 'success' : 'info'">
            {{ state.status.keyboard[binding.action] ? '已注册' : state.settings.keyboard[binding.action] ? '不可用' : '已禁用' }}
          </el-tag>
        </div>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { CircleClose, Refresh } from '@element-plus/icons-vue'
import type { InputBindingRegistrationStatus, InputBindingSettings, KeyboardShortcutAction, MouseSideButton } from '@/../shared/input-bindings'

const props = defineProps<{
  state: {
    settings: InputBindingSettings
    status: InputBindingRegistrationStatus
    available: boolean
    loading: boolean
  }
}>()

defineEmits<{
  reset: []
  'set-push-to-talk-enabled': [enabled: boolean]
  'set-push-to-talk-mouse-button': [button: MouseSideButton]
  'capture-keyboard': [action: KeyboardShortcutAction, event: KeyboardEvent]
  'clear-keyboard': [action: KeyboardShortcutAction]
}>()

const state = props.state
const activeKeyboardCapture = ref<KeyboardShortcutAction | null>(null)
const keyboardBindingRows: Array<{ action: KeyboardShortcutAction; label: string }> = [
  { action: 'interact', label: '切换拖动模式' },
  { action: 'lock', label: '锁定桌宠位置' },
  { action: 'openPanel', label: '打开陪伴面板' },
  { action: 'toggleVision', label: '暂停或恢复视觉' },
]
</script>

<style scoped>
.desktop-input-card { margin-top: 16px; }
.desktop-input-form { display: flex; flex-direction: column; gap: 14px; margin-top: 14px; }
.desktop-input-row,
.keyboard-binding-row { display: grid; grid-template-columns: minmax(180px, 1fr) auto minmax(220px, 300px); align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--yui-border); }
.keyboard-binding-row { grid-template-columns: minmax(180px, 1fr) minmax(240px, 360px) auto; }
.keyboard-binding-list { display: flex; flex-direction: column; }
.desktop-input-select { width: 100%; }
.card-header,
.button-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
.button-row { justify-content: flex-start; flex-wrap: wrap; }
.header-title { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
@media (max-width: 960px) {
  .desktop-input-row,
  .keyboard-binding-row { grid-template-columns: 1fr; }
  .card-header { align-items: flex-start; flex-direction: column; }
}
</style>

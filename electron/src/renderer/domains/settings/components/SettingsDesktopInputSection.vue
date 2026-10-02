<template>
  <el-card class="desktop-input-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div class="header-title"><span>桌面输入</span></div>
        <div class="button-row">
          <el-tag :type="pushToTalkStatusType">
            {{ pushToTalkStatusLabel }}
          </el-tag>
          <el-button
            :icon="Connection"
            :loading="state.loading"
            title="重新连接桌面输入"
            aria-label="重新连接桌面输入"
            @click="$emit('retry')"
          />
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
      title="桌面应用输入服务尚未连接；快捷键仍可编辑，连接后会自动注册。"
    />
    <el-alert
      v-else-if="state.browserFallback"
      type="info"
      :closable="false"
      :title="state.browserShortcutsEnabled ? '浏览器快捷键和本页鼠标侧键正在监听；全局桌面动作需要桌面应用。' : '本页输入已暂停；桌面应用的全局输入不受影响。'"
    />
    <el-alert
      v-else-if="state.status.errors.length"
      type="warning"
      :closable="false"
      :title="state.status.errors.join('；')"
    />
    <el-alert v-if="state.error" type="error" :closable="false" :title="state.error" />

    <div v-if="state.browserFallback" class="browser-scope-row">
      <div>
        <strong>本页输入</strong>
        <small v-if="state.lastBrowserActionAt" class="field-note browser-feedback">最近触发：{{ lastBrowserActionLabel }}</small>
      </div>
      <el-switch
        data-testid="toggle-browser-input"
        :model-value="state.browserShortcutsEnabled"
        :disabled="state.loading"
        @change="$emit('set-browser-shortcuts-enabled', Boolean($event))"
      />
    </div>

    <el-form class="desktop-input-form" label-position="top" @submit.prevent>
      <div class="desktop-input-row">
        <div>
          <strong>按住说话</strong>
        </div>
        <el-switch
          data-testid="toggle-talk"
          :model-value="state.settings.pushToTalk.enabled"
          :disabled="state.loading"
          @change="$emit('set-push-to-talk-enabled', Boolean($event))"
        />
        <el-select
          data-testid="mouse-button"
          :model-value="state.settings.pushToTalk.mouseButton"
          :disabled="state.loading"
          class="desktop-input-select"
          @change="$emit('set-push-to-talk-mouse-button', Number($event))"
        >
          <el-option label="鼠标侧键 1（后退）" :value="4" />
          <el-option label="鼠标侧键 2（前进）" :value="5" />
        </el-select>
      </div>

      <el-alert
        v-if="state.settings.pushToTalk.enabled"
        class="mouse-hook-warning"
        type="warning"
        :closable="false"
        :title="state.browserFallback ? (state.browserShortcutsEnabled ? '只在当前浏览器页面监听鼠标侧键。' : '本页输入已暂停，不会监听鼠标侧键。') : '已监听全局鼠标侧键，可能影响其他应用的输入。'"
      />

      <div class="desktop-input-row" data-testid="desktop-action-beta">
        <div><strong>桌面动作</strong></div>
        <div class="button-row">
          <el-tag :type="desktopActionStatusType">{{ desktopActionStatusLabel }}</el-tag>
          <el-tag v-if="desktopAction.status.leaseState === 'unconfirmed'" type="danger">尚未授权</el-tag>
          <el-tag v-else-if="desktopAction.status.authorizationGranted" type="success">已授权</el-tag>
        </div>
        <div class="button-row desktop-action-controls">
          <el-switch
            data-testid="desktop-action-toggle"
            :model-value="desktopAction.status.enabled"
            :disabled="!desktopActionControlAvailable || desktopAction.loading || desktopAction.status.operationInFlight || desktopAction.status.emergencyStopped"
            @change="setDesktopActionEnabled(Boolean($event))"
          />
          <el-button
            v-if="desktopAction.status.emergencyStopped"
            data-testid="desktop-action-rearm"
            :loading="desktopAction.loading"
            :disabled="!desktopActionControlAvailable"
            @click="runDesktopAction('rearm')"
          >
            重新启用
          </el-button>
          <el-button
            v-if="desktopAction.status.enabled"
            data-testid="desktop-action-manage-authorization"
            :loading="desktopAction.loading"
            :disabled="!desktopActionControlAvailable || desktopAction.status.leaseState !== 'confirmed'"
            @click="runDesktopAction('manageAuthorization')"
          >
            管理授权
          </el-button>
          <el-button
            data-testid="desktop-action-refresh"
            :icon="Refresh"
            :loading="desktopAction.loading"
            :disabled="!desktopAction.available"
            title="刷新桌面动作状态"
            aria-label="刷新桌面动作状态"
            @click="runDesktopAction('status')"
          />
        </div>
        <el-alert
          v-if="desktopAction.status.degraded || desktopAction.status.lastError"
          class="desktop-action-error"
          data-testid="desktop-action-error"
          type="error"
          :closable="false"
          :title="desktopAction.status.lastError?.message || desktopAction.status.reason || '桌面动作暂不可用'"
        />
      </div>

      <div class="keyboard-binding-list">
        <div v-for="binding in keyboardBindingRows" :key="binding.action" class="keyboard-binding-row">
          <div>
            <strong>{{ binding.label }}</strong>
          </div>
          <el-input
            :data-testid="binding.action === 'interact' ? 'shortcut' : undefined"
            :model-value="draftValues[binding.action]"
            :placeholder="activeKeyboardCapture === binding.action ? '请按下组合键' : '点击后按下组合键'"
            :disabled="state.loading"
            :readonly="editingAction !== binding.action"
            @update:model-value="draftValues[binding.action] = String($event)"
            @click="activeKeyboardCapture = binding.action"
            @focus="activeKeyboardCapture = binding.action"
            @blur="finishCapture(binding.action)"
            @keydown="handleKeydown(binding.action, $event)"
          >
            <template #append>
              <div class="binding-actions">
                <el-button
                  :icon="editingAction === binding.action ? Check : Edit"
                  :title="editingAction === binding.action ? '保存编辑' : '编辑快捷键'"
                  :aria-label="editingAction === binding.action ? '保存编辑' : '编辑快捷键'"
                  @mousedown.prevent
                  @click="toggleEditing(binding.action)"
                />
                <el-button
                  :icon="CircleClose"
                  :disabled="!state.settings.keyboard[binding.action]"
                  :title="`清除${binding.label}`"
                  :aria-label="`清除${binding.label}`"
                  @mousedown.prevent
                  @click="clearBinding(binding.action)"
                />
              </div>
            </template>
          </el-input>
          <el-tag :type="bindingStatus(binding.action).type">
            {{ bindingStatus(binding.action).label }}
          </el-tag>
        </div>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSwitch } from 'element-plus'
import 'element-plus/es/components/switch/style/css'
import { ElInput, ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/input/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { ElForm } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Check, CircleClose, Connection, Edit, Refresh } from '@element-plus/icons-vue'
import type { InputBindingRegistrationStatus, InputBindingSettings, KeyboardShortcutAction, MouseSideButton } from '@/../shared/input-bindings'
import type { DesktopActionResult, DesktopActionStatus } from '@/../shared/desktop-action'

const props = defineProps<{
  state: {
    settings: InputBindingSettings
    status: InputBindingRegistrationStatus
    available: boolean
    browserFallback?: boolean
    browserShortcutsEnabled: boolean
    lastBrowserAction: string | null
    lastBrowserActionAt: number
    loading: boolean
    error?: string
  }
}>()

const emit = defineEmits<{
  reset: []
  'set-push-to-talk-enabled': [enabled: boolean]
  'set-push-to-talk-mouse-button': [button: MouseSideButton]
  'set-browser-shortcuts-enabled': [enabled: boolean]
  'capture-keyboard': [action: KeyboardShortcutAction, event: KeyboardEvent]
  'clear-keyboard': [action: KeyboardShortcutAction]
  'set-keyboard': [action: KeyboardShortcutAction, value: string]
  retry: []
}>()

const state = props.state
const defaultDesktopActionStatus = (): DesktopActionStatus => ({
  enabled: false,
  windowActionsAvailable: false,
  nativeInputAvailable: false,
  emergencyHotkeyAvailable: false,
  emergencyStopped: false,
  revision: 0,
  stopEpoch: 0,
  operationInFlight: false,
  degraded: false,
  leaseState: 'inactive',
  leaseExpiresAt: null,
  lastHeartbeatAt: null,
  authorizationGranted: false,
  authorizationExpiresAt: null,
  reason: null,
  lastError: null,
})
const desktopAction = reactive({
  available: Boolean(window.petApi?.desktopAction),
  loading: false,
  status: defaultDesktopActionStatus(),
})
const desktopActionStatusLabel = computed(() => {
  if (!desktopActionControlAvailable.value) return '不可用'
  if (desktopAction.status.emergencyStopped) return '已停止'
  return desktopAction.status.enabled ? '已启用' : '已关闭'
})
const desktopActionControlAvailable = computed(() => (
  desktopAction.available
  && desktopAction.status.windowActionsAvailable
  && desktopAction.status.emergencyHotkeyAvailable
))
const desktopActionStatusType = computed(() => {
  if (desktopAction.status.enabled) return 'success'
  if (desktopAction.status.emergencyStopped) return 'danger'
  return desktopAction.status.windowActionsAvailable ? 'info' : 'warning'
})

const applyDesktopActionResult = (result: DesktopActionResult<DesktopActionStatus>) => {
  desktopAction.status = result.status
}

const runDesktopAction = async (operation: 'status' | 'enable' | 'disable' | 'rearm' | 'manageAuthorization') => {
  const api = window.petApi?.desktopAction
  if (!api || desktopAction.loading) return
  desktopAction.loading = true
  try {
    applyDesktopActionResult(await api[operation]())
  } catch {
    desktopAction.status = { ...desktopAction.status, degraded: true }
  } finally {
    desktopAction.loading = false
  }
}

const setDesktopActionEnabled = (enabled: boolean) => {
  void runDesktopAction(enabled ? 'enable' : 'disable')
}

const activeKeyboardCapture = ref<KeyboardShortcutAction | null>(null)
const editingAction = ref<KeyboardShortcutAction | null>(null)
const draftValues = reactive<Record<KeyboardShortcutAction, string>>({
  interact: '',
  lock: '',
  openPanel: '',
  toggleVision: '',
  emergencyStop: '',
})

const pushToTalkStatusLabel = computed(() => {
  if (state.browserFallback) {
    if (!state.browserShortcutsEnabled) return '本页输入已暂停'
    return state.settings.pushToTalk.enabled ? '本页按住说话' : '鼠标输入未启用'
  }
  if (!state.settings.pushToTalk.enabled) return '鼠标输入未启用'
  if (state.loading) return '正在连接鼠标监听'
  return state.status.pushToTalkActive ? '侧键监听可用' : '侧键监听不可用'
})
const pushToTalkStatusType = computed<'success' | 'warning' | 'info'>(() => {
  if (state.browserFallback && !state.browserShortcutsEnabled) return 'info'
  if (state.browserFallback && state.settings.pushToTalk.enabled) return 'success'
  if (state.status.pushToTalkActive) return 'success'
  if (!state.settings.pushToTalk.enabled) return 'info'
  return 'warning'
})

const lastBrowserActionLabel = computed(() => ({
  interact: '拖动模式',
  lock: '锁定桌宠',
  openPanel: '打开陪伴面板',
  toggleVision: '切换视觉',
  emergencyStop: '紧急停止',
  startVoice: '开始按住说话',
  stopVoice: '结束按住说话',
}[state.lastBrowserAction || ''] || '输入动作'))

const bindingStatus = (action: KeyboardShortcutAction): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } => {
  const value = state.settings.keyboard[action]
  if (!value) return { label: '已禁用', type: 'info' }
  if (state.browserFallback) {
    return state.browserShortcutsEnabled
      ? { label: '本页监听中', type: 'success' }
      : { label: '已暂停', type: 'info' }
  }
  if (state.status.keyboard[action]) return { label: '已注册', type: 'success' }
  return { label: '注册失败', type: 'danger' }
}

const toggleEditing = (action: KeyboardShortcutAction) => {
  if (editingAction.value === action) {
    finishCapture(action)
    return
  }
  editingAction.value = action
  activeKeyboardCapture.value = null
  draftValues[action] = state.settings.keyboard[action]
}

const clearBinding = (action: KeyboardShortcutAction) => {
  editingAction.value = null
  activeKeyboardCapture.value = null
  emit('clear-keyboard', action)
}

const finishCapture = (action: KeyboardShortcutAction) => {
  if (editingAction.value === action) {
    const value = draftValues[action].trim()
    emit('set-keyboard', action, value)
    editingAction.value = null
    draftValues[action] = state.settings.keyboard[action]
  }
  if (activeKeyboardCapture.value === action) activeKeyboardCapture.value = null
}

watch(() => state.settings.keyboard, (keyboard) => {
  if (editingAction.value) return
  for (const binding of keyboardBindingRows) draftValues[binding.action] = keyboard[binding.action]
}, { deep: true })

const handleKeydown = (action: KeyboardShortcutAction, event: KeyboardEvent) => {
  if (editingAction.value === action) {
    if (event.key === 'Enter') {
      event.preventDefault()
      finishCapture(action)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      draftValues[action] = state.settings.keyboard[action]
      editingAction.value = null
      activeKeyboardCapture.value = null
    }
    return
  }
  event.preventDefault()
  emit('capture-keyboard', action, event)
  activeKeyboardCapture.value = null
}
const keyboardBindingRows: Array<{ action: KeyboardShortcutAction; label: string }> = [
  { action: 'emergencyStop', label: '紧急停止' },
  { action: 'interact', label: '切换拖动模式' },
  { action: 'lock', label: '锁定桌宠位置' },
  { action: 'openPanel', label: '打开陪伴面板' },
  { action: 'toggleVision', label: '暂停或恢复视觉' },
]

onMounted(() => {
  for (const binding of keyboardBindingRows) draftValues[binding.action] = state.settings.keyboard[binding.action]
  void runDesktopAction('status')
})
</script>

<style scoped>
.desktop-input-card { margin-top: 16px; }
.desktop-input-form { display: flex; flex-direction: column; gap: 14px; margin-top: 14px; }
.browser-scope-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--yui-border); }
.browser-feedback { color: var(--yui-success, #2f8f5b); }
.desktop-input-row,
.keyboard-binding-row { display: grid; grid-template-columns: minmax(180px, 1fr) auto minmax(220px, 300px); align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--yui-border); }
.keyboard-binding-row { grid-template-columns: minmax(180px, 1fr) minmax(240px, 360px) auto; }
.keyboard-binding-list { display: flex; flex-direction: column; }
.binding-actions { display: flex; align-items: center; gap: 2px; }
.keyboard-binding-row :deep(.el-input-group__append) { padding: 0 4px; }
.desktop-input-select { width: 100%; }
.field-note { display: block; margin-top: 4px; color: var(--yui-muted); font-size: 11px; line-height: 1.4; }
.desktop-action-controls { justify-content: flex-end; }
.desktop-action-error { grid-column: 1 / -1; }
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

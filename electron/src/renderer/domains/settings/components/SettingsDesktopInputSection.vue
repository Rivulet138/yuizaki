<template>
  <el-card class="desktop-input-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div class="header-title"><span>{{ t('settingsSection.desktopInput.title') }}</span></div>
        <div class="button-row">
          <el-tag :type="pushToTalkStatusType">
            {{ pushToTalkStatusLabel }}
          </el-tag>
          <el-button
            :icon="Connection"
            :loading="state.loading"
            :title="t('settingsSection.desktopInput.reconnect')"
            :aria-label="t('settingsSection.desktopInput.reconnect')"
            @click="$emit('retry')"
          />
          <el-button
            data-testid="reset-input-bindings"
            :icon="Refresh"
            :loading="state.loading"
            :title="t('settingsSection.desktopInput.resetShortcuts')"
            :aria-label="t('settingsSection.desktopInput.resetShortcuts')"
            @click="$emit('reset')"
          />
        </div>
      </div>
    </template>

    <el-alert
      v-if="!state.available"
      type="info"
      :closable="false"
      :title="t('settingsSection.desktopInput.unavailable')"
    />
    <el-alert
      v-else-if="state.browserFallback"
      type="info"
      :closable="false"
      :title="state.browserShortcutsEnabled ? t('settingsSection.desktopInput.browserActive') : t('settingsSection.desktopInput.browserPaused')"
    />
    <el-alert
      v-else-if="state.status.errors.length"
      type="warning"
      :closable="false"
      :title="state.status.errors.join(t('settingsSection.desktopInput.errorSeparator'))"
    />
    <el-alert v-if="state.error" type="error" :closable="false" :title="state.error" />

    <div v-if="state.browserFallback" class="browser-scope-row">
      <div>
        <strong>{{ t('settingsSection.desktopInput.pageInput') }}</strong>
        <small v-if="state.lastBrowserActionAt" class="field-note browser-feedback">{{ t('settingsSection.desktopInput.lastTriggered', { label: lastBrowserActionLabel }) }}</small>
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
          <strong>{{ t('settingsSection.desktopInput.pushToTalk') }}</strong>
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
          <el-option :label="t('settingsSection.desktopInput.mouseButtonBack')" :value="4" />
          <el-option :label="t('settingsSection.desktopInput.mouseButtonForward')" :value="5" />
        </el-select>
      </div>

      <el-alert
        v-if="state.settings.pushToTalk.enabled"
        class="mouse-hook-warning"
        type="warning"
        :closable="false"
        :title="state.browserFallback ? (state.browserShortcutsEnabled ? t('settingsSection.desktopInput.mouseHookBrowserEnabled') : t('settingsSection.desktopInput.mouseHookBrowserPaused')) : t('settingsSection.desktopInput.mouseHookGlobal')"
      />

      <div class="desktop-input-row" data-testid="desktop-action-beta">
        <div><strong>{{ t('settingsSection.desktopInput.desktopAction') }}</strong></div>
        <div class="button-row">
          <el-tag :type="desktopActionStatusType">{{ desktopActionStatusLabel }}</el-tag>
          <el-tag v-if="desktopAction.status.leaseState === 'unconfirmed'" type="danger">{{ t('settingsSection.desktopInput.authPending') }}</el-tag>
          <el-tag v-else-if="desktopAction.status.authorizationGranted" type="success">{{ t('settingsSection.desktopInput.authGranted') }}</el-tag>
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
            {{ t('settingsSection.desktopInput.rearm') }}
          </el-button>
          <el-button
            v-if="desktopAction.status.enabled"
            data-testid="desktop-action-manage-authorization"
            :loading="desktopAction.loading"
            :disabled="!desktopActionControlAvailable || desktopAction.status.leaseState !== 'confirmed'"
            @click="runDesktopAction('manageAuthorization')"
          >
            {{ t('settingsSection.desktopInput.manageAuth') }}
          </el-button>
          <el-button
            data-testid="desktop-action-refresh"
            :icon="Refresh"
            :loading="desktopAction.loading"
            :disabled="!desktopAction.available"
            :title="t('settingsSection.desktopInput.refreshStatus')"
            :aria-label="t('settingsSection.desktopInput.refreshStatus')"
            @click="runDesktopAction('status')"
          />
        </div>
        <el-alert
          v-if="desktopAction.status.degraded || desktopAction.status.lastError"
          class="desktop-action-error"
          data-testid="desktop-action-error"
          type="error"
          :closable="false"
          :title="desktopAction.status.lastError?.message || desktopAction.status.reason || t('settingsSection.desktopInput.actionUnavailable')"
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
            :placeholder="activeKeyboardCapture === binding.action ? t('settingsSection.desktopInput.pressKeys') : t('settingsSection.desktopInput.clickThenPressKeys')"
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
                  :title="editingAction === binding.action ? t('settingsSection.desktopInput.saveEdit') : t('settingsSection.desktopInput.editShortcut')"
                  :aria-label="editingAction === binding.action ? t('settingsSection.desktopInput.saveEdit') : t('settingsSection.desktopInput.editShortcut')"
                  @mousedown.prevent
                  @click="toggleEditing(binding.action)"
                />
                <el-button
                  :icon="CircleClose"
                  :disabled="!state.settings.keyboard[binding.action]"
                  :title="t('settingsSection.desktopInput.clearBinding', { label: binding.label })"
                  :aria-label="t('settingsSection.desktopInput.clearBinding', { label: binding.label })"
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
import { t } from '@/i18n'
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
  if (!desktopActionControlAvailable.value) return t('settingsSection.desktopInput.statusUnavailable')
  if (desktopAction.status.emergencyStopped) return t('settingsSection.desktopInput.statusStopped')
  return desktopAction.status.enabled ? t('settingsSection.desktopInput.statusEnabled') : t('settingsSection.desktopInput.statusDisabled')
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
    if (!state.browserShortcutsEnabled) return t('settingsSection.desktopInput.browserInputPaused')
    return state.settings.pushToTalk.enabled ? t('settingsSection.desktopInput.browserPushToTalk') : t('settingsSection.desktopInput.mouseInputDisabled')
  }
  if (!state.settings.pushToTalk.enabled) return t('settingsSection.desktopInput.mouseInputDisabled')
  if (state.loading) return t('settingsSection.desktopInput.connectingMouse')
  return state.status.pushToTalkActive ? t('settingsSection.desktopInput.sideButtonListening') : t('settingsSection.desktopInput.sideButtonUnavailable')
})
const pushToTalkStatusType = computed<'success' | 'warning' | 'info'>(() => {
  if (state.browserFallback && !state.browserShortcutsEnabled) return 'info'
  if (state.browserFallback && state.settings.pushToTalk.enabled) return 'success'
  if (state.status.pushToTalkActive) return 'success'
  if (!state.settings.pushToTalk.enabled) return 'info'
  return 'warning'
})

const lastBrowserActionLabel = computed(() => ({
  interact: t('settingsSection.desktopInput.lastActionInteract'),
  lock: t('settingsSection.desktopInput.lastActionLock'),
  openPanel: t('settingsSection.desktopInput.lastActionOpenPanel'),
  toggleVision: t('settingsSection.desktopInput.lastActionToggleVision'),
  emergencyStop: t('settingsSection.desktopInput.lastActionEmergencyStop'),
  startVoice: t('settingsSection.desktopInput.lastActionStartVoice'),
  stopVoice: t('settingsSection.desktopInput.lastActionStopVoice'),
}[state.lastBrowserAction || ''] || t('settingsSection.desktopInput.lastActionUnknown')))

const bindingStatus = (action: KeyboardShortcutAction): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } => {
  const value = state.settings.keyboard[action]
  if (!value) return { label: t('settingsSection.desktopInput.shortcutDisabled'), type: 'info' }
  if (state.browserFallback) {
    return state.browserShortcutsEnabled
      ? { label: t('settingsSection.desktopInput.listeningInPage'), type: 'success' }
      : { label: t('settingsSection.desktopInput.paused'), type: 'info' }
  }
  if (state.status.keyboard[action]) return { label: t('settingsSection.desktopInput.registered'), type: 'success' }
  return { label: t('settingsSection.desktopInput.registerFailed'), type: 'danger' }
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
  for (const binding of keyboardBindingRows.value) draftValues[binding.action] = keyboard[binding.action]
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
const keyboardBindingRows = computed<Array<{ action: KeyboardShortcutAction; label: string }>>(() => [
  { action: 'emergencyStop', label: t('settingsSection.desktopInput.bindingEmergencyStop') },
  { action: 'interact', label: t('settingsSection.desktopInput.bindingInteract') },
  { action: 'lock', label: t('settingsSection.desktopInput.bindingLock') },
  { action: 'openPanel', label: t('settingsSection.desktopInput.bindingOpenPanel') },
  { action: 'toggleVision', label: t('settingsSection.desktopInput.bindingToggleVision') },
])

onMounted(() => {
  for (const binding of keyboardBindingRows.value) draftValues[binding.action] = state.settings.keyboard[binding.action]
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

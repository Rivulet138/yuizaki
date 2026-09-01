<template>
  <PanelShell :title="t('navigation.svc.title')">
    <div class="voice-panel">
      <section class="voice-toolbar">
        <div>
          <strong>{{ runtimeSummary }}</strong>
        </div>
        <div class="toolbar-actions">
          <el-tag :type="selectedFile ? 'success' : 'info'">{{ selectedFile ? selectedFile.name : t('svcPanel.noAudio') }}</el-tag>
          <el-button :loading="settingsLoading" :disabled="settingsLoading" @click="loadSettings">{{ t('svcPanel.refreshSettings') }}</el-button>
        </div>
      </section>
      <el-alert v-if="voiceSaveStatusVisible" :title="voiceSaveStatusLabel" :description="voiceSaveStatusDetail" :type="voiceSaveAlertType" show-icon :closable="false" />

      <section class="voice-grid">
        <el-card class="voice-card svc-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div>
                <strong>{{ svcProviderLabel }}</strong>
              </div>
              <el-tag :type="svcModelReady ? 'success' : 'warning'">{{ svcReadinessLabel }}</el-tag>
            </div>
          </template>

          <el-upload drag action="#" :auto-upload="false" :show-file-list="false" accept="audio/*" :on-change="handleFileChange">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">{{ t('svcPanel.dropAudio') }}</div>
            <template #tip>
              <div class="el-upload__tip">{{ t('svcPanel.uploadTip') }}</div>
            </template>
          </el-upload>

          <el-form class="svc-form" label-position="top" @submit.prevent>
            <el-form-item :label="t('settings.svc.provider')">
              <el-select v-model="voiceConfig.svc.provider" @change="saveSvcProvider">
                <el-option label="SoulX-Singer-SVC Service" value="soulx-service" />
                <el-option :label="t('common.disabled')" value="disabled" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('settings.svc.baseUrl')">
              <el-input v-model="voiceConfig.svc.base_url" @change="saveSvcSettings({ base_url: String($event) })" />
            </el-form-item>
            <div class="form-row">
              <el-form-item :label="t('settings.svc.referenceAudioId')">
                <el-input-number v-model="voiceConfig.svc.speaker_id" :min="0" controls-position="right" @change="saveSvcSettings({ speaker_id: Number($event) })" />
              </el-form-item>
            </div>
            <el-form-item :label="t('svcPanel.pitchShiftValue', { value: `${conversionPitch > 0 ? '+' : ''}${conversionPitch}` })">
              <el-slider v-model="conversionPitch" :min="-36" :max="36" show-stops @change="saveSvcPitch" />
            </el-form-item>
          </el-form>

          <div class="execution-area">
            <el-button type="primary" :loading="isConverting" :disabled="!canStartConversion" @click="startConversion">
              {{ isConverting ? t('svcPanel.converting') : t('svcPanel.startConversion') }}
            </el-button>
            <el-alert
              v-if="svcReadinessMessage"
              :title="svcReadinessMessage"
              type="warning"
              show-icon
              :closable="false"
            />
            <el-alert v-if="conversionError" :title="conversionError" type="error" show-icon :closable="false" />
            <el-alert v-if="resultAudioUrl" :title="t('svcPanel.conversionComplete')" type="success" show-icon :closable="false" />
            <audio v-if="resultAudioUrl" :src="resultAudioUrl" controls class="audio-player"></audio>
          </div>
        </el-card>

      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { API_ORIGIN, requestJson, resolveBackendUrl } from '@/api/clients/http-client'
import { settingsClient, type SettingsResponse } from '@/api/clients/settings-client'

interface SvcConvertResponse {
  status?: string
  audio_url?: string
  url?: string
  error?: string
}

type SaveTimeout = ReturnType<typeof window.setTimeout>
type SettingsPatch = Record<string, unknown>
type AlertType = 'success' | 'warning' | 'info' | 'error'
type SvcSettingsPatch = Partial<SettingsResponse['svc']>

const defaultVoiceConfig: Pick<SettingsResponse, 'svc'> = {
  svc: {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
}

const voiceConfig = reactive<Pick<SettingsResponse, 'svc'>>(structuredClone(defaultVoiceConfig))
const selectedFile = ref<File | null>(null)
const settingsLoading = ref(false)
const isConverting = ref(false)
const conversionPitch = ref(0)
const resultAudioUrl = ref('')
const conversionError = ref('')
const voiceSaveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const voiceSaveError = ref('')
const voiceLastSavedAt = ref('')
const voiceLastApplied = ref<string[]>([])
const pendingSavePatch = ref<SettingsPatch | null>(null)
let saveTimeout: SaveTimeout | null = null
let settingsLoadSequence = 0
let unmounted = false

const isPlainRecord = (value: unknown): value is SettingsPatch => {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const mergePatch = (base: SettingsPatch, patch: SettingsPatch): SettingsPatch => {
  const merged: SettingsPatch = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    const existing = merged[key]
    merged[key] = isPlainRecord(existing) && isPlainRecord(value)
      ? mergePatch(existing, value)
      : value
  }
  return merged
}

const svcModelReady = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return false
  return Boolean(voiceConfig.svc.base_url.trim())
})
const svcProviderLabel = computed(() => voiceConfig.svc.provider === 'disabled' ? t('svcPanel.svcDisabled') : 'SoulX-Singer-SVC Service')
const svcReadinessLabel = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.svcDisabled')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.endpointMissing')
  return t('svcPanel.serviceConfigured')
})
const svcReadinessMessage = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.enableSvcFirst')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.configureEndpointFirst')
  return ''
})
const canStartConversion = computed(() => {
  return Boolean(selectedFile.value && svcModelReady.value && !isConverting.value)
})
const runtimeSummary = computed(() => `SoulX · ${voiceConfig.svc.provider}`)
const voiceSaveStatusVisible = computed(() => voiceSaveStatus.value !== 'idle')
const voiceSaveAlertType = computed<AlertType>(() => {
  if (voiceSaveStatus.value === 'error') return 'error'
  if (voiceSaveStatus.value === 'saving') return 'warning'
  if (voiceSaveStatus.value === 'saved') return 'success'
  return 'info'
})
const voiceSaveStatusLabel = computed(() => {
  if (voiceSaveStatus.value === 'saving') return t('settings.status.saving')
  if (voiceSaveStatus.value === 'error') return t('svcPanel.saveFailed')
  if (voiceSaveStatus.value === 'saved') return t('settings.status.saved')
  return ''
})
const voiceSaveStatusDetail = computed(() => {
  if (voiceSaveStatus.value === 'error') return voiceSaveError.value
  if (voiceSaveStatus.value === 'saving') return t('settings.status.savingShort')
  if (voiceLastApplied.value.length) return t('settings.status.applied', { items: voiceLastApplied.value.join(' / ') })
  if (voiceLastSavedAt.value) return t('settings.status.recent', { time: voiceLastSavedAt.value })
  return ''
})

const applySettings = (settings: SettingsResponse) => {
  Object.assign(voiceConfig.svc, settings.svc)
  conversionPitch.value = settings.svc.pitch
}

const loadSettings = async () => {
  const requestId = ++settingsLoadSequence
  settingsLoading.value = true
  try {
    const settings = await settingsClient.load()
    if (unmounted || requestId !== settingsLoadSequence) return
    applySettings(settings)
  } catch (error) {
    if (unmounted || requestId !== settingsLoadSequence) return
    ElMessage.error(error instanceof Error ? error.message : t('svcPanel.loadFailed'))
  } finally {
    if (!unmounted && requestId === settingsLoadSequence) settingsLoading.value = false
  }
}

const errorMessage = (error: unknown, fallback: string) => {
  return error instanceof Error ? error.message : fallback
}

const savePatch = async (patch: SettingsPatch) => {
  if (!unmounted) {
    voiceSaveStatus.value = 'saving'
    voiceSaveError.value = ''
  }
  try {
    const result = await settingsClient.save(patch)
    if (unmounted) return true
    voiceLastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    voiceLastApplied.value = result.runtime_applied || result.runtime_changed || []
    voiceSaveStatus.value = 'saved'
    return true
  } catch (error) {
    if (unmounted) {
      console.error('[SVCPanel Save]:', error)
      return false
    }
    voiceSaveError.value = errorMessage(error, t('svcPanel.saveFailed'))
    voiceSaveStatus.value = 'error'
    ElMessage.error(voiceSaveError.value)
    return false
  }
}

const scheduleSave = (patch: SettingsPatch) => {
  if (unmounted) return
  if (saveTimeout) clearTimeout(saveTimeout)
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(pendingSavePatch.value, patch)
    : patch

  saveTimeout = setTimeout(async () => {
    const currentPatch = pendingSavePatch.value
    pendingSavePatch.value = null
    if (currentPatch) await savePatch(currentPatch)
  }, 800)
}

const flushPendingSave = async () => {
  if (!pendingSavePatch.value) return true
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  const currentPatch = pendingSavePatch.value
  pendingSavePatch.value = null
  return savePatch(currentPatch)
}

const saveSvcSettings = (patch: SvcSettingsPatch) => {
  scheduleSave({ svc: patch })
}

const saveSvcProvider = (value: string | number | boolean) => {
  const provider = String(value) as SettingsResponse['svc']['provider']
  voiceConfig.svc.provider = provider
  saveSvcSettings({ provider })
}

const saveSvcPitch = (value: number | number[]) => {
  const pitch = Array.isArray(value) ? value[0] ?? 0 : value
  voiceConfig.svc.pitch = pitch
  saveSvcSettings({ pitch })
}

const handleFileChange = (uploadFile: UploadFile) => {
  selectedFile.value = uploadFile.raw ?? null
  resultAudioUrl.value = ''
  conversionError.value = ''
}

const normalizeAudioUrl = async (audioUrl: string) => {
  if (!audioUrl) return ''
  if (audioUrl.startsWith('http://') || audioUrl.startsWith('https://')) return audioUrl
  return resolveBackendUrl(audioUrl)
}

const startConversion = async () => {
  if (isConverting.value) return
  if (!selectedFile.value) {
    ElMessage.warning(t('svcPanel.selectAudioFirst'))
    return
  }
  if (!svcModelReady.value) {
    ElMessage.warning(svcReadinessMessage.value || t('svcPanel.waitingService'))
    return
  }
  if (voiceConfig.svc.pitch !== conversionPitch.value) {
    voiceConfig.svc.pitch = conversionPitch.value
    saveSvcSettings({ pitch: conversionPitch.value })
  }
  if (!(await flushPendingSave())) return
  isConverting.value = true
  resultAudioUrl.value = ''
  conversionError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('speaker_id', String(voiceConfig.svc.speaker_id))
    formData.append('pitch', String(conversionPitch.value))
    const result = await requestJson<SvcConvertResponse>(`${API_ORIGIN}/svc/convert`, { method: 'POST', body: formData })
    if (result.status === 'error') {
      throw new Error(result.error || t('svcPanel.requestFailed', { status: 'error' }))
    }
    resultAudioUrl.value = await normalizeAudioUrl(result.audio_url || result.url || '')
    if (!resultAudioUrl.value) {
      conversionError.value = t('svcPanel.requestDoneNoAudio')
      return
    }
    ElMessage.success(t('svcPanel.svcComplete'))
  } catch (error) {
    conversionError.value = error instanceof Error ? error.message : String(error)
    ElMessage.error(conversionError.value)
  } finally {
    isConverting.value = false
  }
}

onMounted(() => {
  void loadSettings()
})

onUnmounted(() => {
  unmounted = true
  settingsLoadSequence += 1
  if (saveTimeout) clearTimeout(saveTimeout)
  const currentPatch = pendingSavePatch.value
  pendingSavePatch.value = null
  if (currentPatch) void savePatch(currentPatch)
})
</script>

<style scoped>
.voice-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.voice-toolbar,
.voice-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.voice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-radius: var(--yui-radius-card);
  padding: 14px 16px;
}

.voice-toolbar > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.voice-toolbar strong,
.card-header strong {
  color: var(--yui-text);
  font-size: 16px;
}

.toolbar-actions,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-kicker {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.voice-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.upload-icon {
  margin-bottom: 8px;
  color: var(--el-color-primary);
  font-size: 42px;
}

:deep(.el-upload-dragger) {
  border-color: var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--yui-accent);
  background: var(--yui-accent-soft);
}

.svc-form,
.execution-area {
  margin-top: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form-row.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.execution-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.audio-player {
  width: 100%;
}

@media (max-width: 1180px) {
  .voice-grid,
  .form-row,
  .form-row.three {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .voice-toolbar,
  .card-header,
  .toolbar-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

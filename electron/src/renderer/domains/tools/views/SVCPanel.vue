<template>
  <PanelShell :title="t('navigation.svc.title')">
    <div class="voice-panel">
      <section class="voice-toolbar">
        <div class="toolbar-actions">
          <el-tag :type="selectedFile ? 'success' : 'info'">{{ selectedFile ? selectedFile.name : t('svcPanel.noAudio') }}</el-tag>
          <el-button :loading="svcCheckState === 'checking'" :disabled="svcCheckState === 'checking'" @click="testService">{{ t('svcPanel.checkService') }}</el-button>
          <el-button type="primary" plain @click="openSettings">{{ t('svcPanel.openSettings') }}</el-button>
        </div>
      </section>

      <section class="voice-grid">
        <el-card class="voice-card svc-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div>
                <strong>{{ svcProviderLabel }}</strong>
              </div>
              <el-tag :type="svcReadinessType">{{ svcReadinessLabel }}</el-tag>
            </div>
          </template>

          <el-upload drag action="#" :auto-upload="false" :show-file-list="false" accept="audio/*" :on-change="handleFileChange">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">{{ t('svcPanel.dropAudio') }}</div>
          </el-upload>

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
import { ElAlert, ElIcon } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/icon/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElUpload, type UploadFile } from 'element-plus'
import 'element-plus/es/components/upload/style/css'
import { t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { API_ORIGIN, requestJson, resolveBackendUrl } from '@/api/clients/http-client'
import { settingsClient, type SettingsResponse } from '@/api/clients/settings-client'
import { useSettingsStore } from '@/state/settingsStore'
import { useRoute, useRouter } from 'vue-router'

interface SvcConvertResponse {
  status?: string
  audio_url?: string
  url?: string
  error?: string
}

const defaultVoiceConfig: Pick<SettingsResponse, 'svc'> = {
  svc: {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
}

const settingsStore = useSettingsStore()
const route = useRoute()
const router = useRouter()
const voiceConfig = reactive<Pick<SettingsResponse, 'svc'>>(structuredClone(defaultVoiceConfig))
const selectedFile = ref<File | null>(null)
const svcCheckState = ref<'idle' | 'checking' | 'ready' | 'error'>('idle')
const isConverting = ref(false)
const resultAudioUrl = ref('')
const conversionError = ref('')
let settingsLoadSequence = 0
let unmounted = false

const svcModelReady = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return false
  return Boolean(voiceConfig.svc.base_url.trim())
})
const svcProviderLabel = computed(() => voiceConfig.svc.provider === 'disabled' ? t('svcPanel.svcDisabled') : t('settings.svc.providerSoulx'))
const svcReadinessLabel = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.svcDisabled')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.endpointMissing')
  if (svcCheckState.value === 'ready') return t('svcPanel.serviceReachable')
  if (svcCheckState.value === 'error') return t('svcPanel.serviceUnavailable')
  if (svcCheckState.value === 'checking') return t('svcPanel.checkingService')
  return t('svcPanel.serviceConfigured')
})
const svcReadinessType = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return 'info'
  if (!voiceConfig.svc.base_url.trim() || svcCheckState.value === 'error') return 'warning'
  if (svcCheckState.value === 'ready') return 'success'
  return 'info'
})
const svcReadinessMessage = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.enableSvcFirst')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.configureEndpointFirst')
  return ''
})
const canStartConversion = computed(() => {
  return Boolean(selectedFile.value && svcModelReady.value && !isConverting.value)
})
const applySettings = (settings: SettingsResponse) => {
  Object.assign(settingsStore.state.svc, settings.svc)
  Object.assign(voiceConfig.svc, settings.svc)
}

const loadSettings = async () => {
  const requestId = ++settingsLoadSequence
  try {
    const settings = await settingsClient.load()
    if (unmounted || requestId !== settingsLoadSequence) return
    applySettings(settings)
  } catch (error) {
    if (unmounted || requestId !== settingsLoadSequence) return
    ElMessage.error(error instanceof Error ? error.message : t('svcPanel.loadFailed'))
  }
}

const testService = async () => {
  if (voiceConfig.svc.provider === 'disabled' || !voiceConfig.svc.base_url.trim()) {
    ElMessage.warning(svcReadinessMessage.value || t('svcPanel.configureEndpointFirst'))
    return
  }
  svcCheckState.value = 'checking'
  try {
    const result = await settingsClient.testSvc()
    svcCheckState.value = result.ok ? 'ready' : 'error'
    if (result.ok) {
      ElMessage.success(result.message || t('svcPanel.serviceReachable'))
    } else {
      ElMessage.error(result.message || t('svcPanel.serviceUnavailable'))
    }
  } catch (error) {
    svcCheckState.value = 'error'
    ElMessage.error(error instanceof Error ? error.message : t('svcPanel.serviceUnavailable'))
  }
}

const openSettings = () => {
  const workspaceId = String(route.params.workspaceId || 'default')
  void router.push({
    path: `/w/${encodeURIComponent(workspaceId)}/settings`,
    query: { section: 'svc' },
  })
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

const conversionRequestTimeoutMs = (configuredSeconds: number | undefined): number => {
  const seconds = Number(configuredSeconds)
  if (!Number.isFinite(seconds)) return 120_000
  // The backend uses the same timeout for the upstream SVC call. Keep the
  // browser request alive slightly longer so it can receive the backend result.
  return Math.max(12_000, Math.min(905_000, Math.ceil(seconds * 1000) + 5_000))
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
  isConverting.value = true
  resultAudioUrl.value = ''
  conversionError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const svcSettings = settingsStore.state.svc
    formData.append('speaker_id', String(svcSettings.speaker_id))
    formData.append('pitch', String(svcSettings.pitch))
    const result = await requestJson<SvcConvertResponse>(`${API_ORIGIN}/svc/convert`, {
      method: 'POST',
      body: formData,
      timeoutMs: conversionRequestTimeoutMs(svcSettings.timeout),
    })
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

watch(() => settingsStore.state.svc, (value) => {
  if (unmounted) return
  Object.assign(voiceConfig.svc, value)
  svcCheckState.value = 'idle'
}, { deep: true })

onUnmounted(() => {
  unmounted = true
  settingsLoadSequence += 1
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
  justify-content: flex-end;
  gap: 16px;
  border-radius: var(--yui-radius-card);
  padding: 14px 16px;
}

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

.execution-area {
  margin-top: 16px;
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
  .voice-grid {
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

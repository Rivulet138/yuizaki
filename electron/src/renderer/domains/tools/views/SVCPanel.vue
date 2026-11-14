<template>
  <component :is="embedded ? 'div' : PanelShell" :title="t('navigation.svc.title')" :class="{ 'svc-embedded-panel': embedded }">
    <div class="voice-panel">
      <section class="voice-toolbar">
        <div class="toolbar-actions">
          <el-tag :type="selectedFile ? 'success' : 'info'">{{ selectedFile ? selectedFile.name : t('svcPanel.noAudio') }}</el-tag>
          <el-button
            v-if="showCheckButton"
            :loading="effectiveCheckState === 'checking'"
            :disabled="effectiveCheckState === 'checking'"
            @click="testService"
          >
            {{ t('svcPanel.checkService') }}
          </el-button>
          <el-button v-if="!embedded" type="primary" plain @click="openSettings">{{ t('svcPanel.openSettings') }}</el-button>
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
            <el-alert v-if="resultAudioUrl" :title="`${t('svcPanel.conversionComplete')} · ${conversionContext?.fileName}`" type="success" show-icon :closable="false" />
            <small v-if="conversionContext" class="conversion-context">
              {{ conversionContext.fileName }} · {{ conversionContext.config.provider }} ·
              {{ conversionContext.config.base_url }} · speaker={{ conversionContext.config.speaker_id }} ·
              pitch={{ conversionContext.config.pitch }} · {{ conversionContext.startedAt }} · {{ conversionContext.requestId }}
            </small>
            <el-alert v-if="svcCheckError" :title="svcCheckError" type="warning" show-icon :closable="false" />
            <audio v-if="resultAudioUrl" :src="resultAudioUrl" controls class="audio-player"></audio>
          </div>
        </el-card>

      </section>
    </div>
  </component>
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
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElUpload, type UploadFile } from 'element-plus'
import 'element-plus/es/components/upload/style/css'
import { t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { API_ORIGIN, requestJson, resolveBackendUrl } from '@/api/clients/http-client'
import { settingsClient, type SettingsResponse } from '@/api/clients/settings-client'
import { useSettingsStore } from '@/state/settingsStore'
import { useRoute, useRouter } from 'vue-router'
import { usePanelLifecycle } from '@/app/composables/usePanelLifecycle'
import { describeFailure } from '@/shared/errors/describe-error'

const props = defineProps<{
  embedded?: boolean
  showCheckButton?: boolean
  config?: SettingsResponse['svc']
  beforeAction?: () => boolean | Promise<boolean>
  testLoading?: boolean
  testResult?: {
    ok: boolean
    ready?: boolean
    reachable?: boolean
    message?: string
  } | null
}>()
const embedded = computed(() => props.embedded === true)
const showCheckButton = computed(() => props.showCheckButton !== false)

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
const svcCheckError = ref('')
const conversionContext = ref<{
  requestId: string; fileName: string; startedAt: string; config: SettingsResponse['svc']
} | null>(null)
const configSnapshot = () => ({ ...activeSvcConfig.value })
const sameConfig = (left: SettingsResponse['svc'], right: SettingsResponse['svc']) =>
  left.provider === right.provider && left.base_url === right.base_url &&
  left.speaker_id === right.speaker_id && left.pitch === right.pitch && left.timeout === right.timeout
let serviceCheckSequence = 0
let settingsLoadSequence = 0
let unmounted = false

const activeSvcConfig = computed(() => props.config ?? voiceConfig.svc)
const effectiveCheckState = computed<'idle' | 'checking' | 'ready' | 'error'>(() => {
  if (!embedded.value) return svcCheckState.value
  if (svcCheckState.value !== 'idle') return svcCheckState.value
  if (props.testLoading) return 'checking'
  // Settings projects the backend's ready-derived `ok` into this prop.
  if (props.testResult) return props.testResult.ok && props.testResult.ready !== false && props.testResult.reachable !== false ? 'ready' : 'error'
  return 'idle'
})
const svcModelReady = computed(() => {
  if (activeSvcConfig.value.provider === 'disabled') return false
  return Boolean(activeSvcConfig.value.base_url.trim())
})
const svcProviderLabel = computed(() => activeSvcConfig.value.provider === 'disabled' ? t('svcPanel.svcDisabled') : t('settings.svc.providerSoulx'))
const svcReadinessLabel = computed(() => {
  if (activeSvcConfig.value.provider === 'disabled') return t('svcPanel.svcDisabled')
  if (!activeSvcConfig.value.base_url.trim()) return t('svcPanel.endpointMissing')
  if (effectiveCheckState.value === 'ready') return t('svcPanel.serviceReachable')
  if (effectiveCheckState.value === 'error') return t('svcPanel.serviceUnavailable')
  if (effectiveCheckState.value === 'checking') return t('svcPanel.checkingService')
  return t('svcPanel.serviceConfigured')
})
const svcReadinessType = computed(() => {
  if (activeSvcConfig.value.provider === 'disabled') return 'info'
  if (!activeSvcConfig.value.base_url.trim() || effectiveCheckState.value === 'error') return 'warning'
  if (effectiveCheckState.value === 'ready') return 'success'
  return 'info'
})
const svcReadinessMessage = computed(() => {
  if (activeSvcConfig.value.provider === 'disabled') return t('svcPanel.enableSvcFirst')
  if (!activeSvcConfig.value.base_url.trim()) return t('svcPanel.configureEndpointFirst')
  return ''
})
const canStartConversion = computed(() => {
  return Boolean(selectedFile.value && svcModelReady.value && !isConverting.value)
})
const applySettings = (settings: SettingsResponse) => {
  Object.assign(settingsStore.state.svc, settings.svc)
  Object.assign(voiceConfig.svc, settings.svc)
}

const runBeforeAction = async () => {
  if (!props.beforeAction) return true
  try {
    return await props.beforeAction()
  } catch (error) {
    conversionError.value = describeFailure(error, t('svcPanel.saveFailed'))
    return false
  }
}

const loadSettings = async () => {
  const requestId = ++settingsLoadSequence
  try {
    const settings = await settingsClient.load()
    if (unmounted || requestId !== settingsLoadSequence) return
    applySettings(settings)
  } catch (error) {
    if (unmounted || requestId !== settingsLoadSequence) return
    ElMessage.error(describeFailure(error, t('svcPanel.loadFailed')))
  }
}

const testService = async () => {
  const svcSettings = configSnapshot()
  if (svcSettings.provider === 'disabled' || !svcSettings.base_url.trim()) {
    svcCheckError.value = svcReadinessMessage.value || t('svcPanel.configureEndpointFirst')
    return
  }
  const requestId = ++serviceCheckSequence
  svcCheckState.value = 'checking'
  svcCheckError.value = ''
  try {
    if (!(await runBeforeAction())) throw new Error(conversionError.value || t('svcPanel.saveFailed'))
    const saved = await settingsClient.load()
    if (unmounted || requestId !== serviceCheckSequence) return
    if (!sameConfig(svcSettings, saved.svc)) throw new Error(t('svcPanel.saveFailed'))
    const result = await settingsClient.testSvc()
    if (unmounted || requestId !== serviceCheckSequence || !sameConfig(svcSettings, activeSvcConfig.value)) return
    const ready = result.ok === true && result.ready === true && result.reachable === true
    svcCheckState.value = ready ? 'ready' : 'error'
    if (ready) ElMessage.success(result.message || t('svcPanel.serviceReachable'))
    else svcCheckError.value = result.message || t('svcPanel.serviceUnavailable')
  } catch (error) {
    if (unmounted || requestId !== serviceCheckSequence) return
    svcCheckState.value = 'error'
    svcCheckError.value = describeFailure(error, t('svcPanel.serviceUnavailable'))
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
  // An in-flight result keeps its own file/config label when another file is selected.
  if (!isConverting.value) {
    resultAudioUrl.value = ''
    conversionError.value = ''
    conversionContext.value = null
  }
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
  const file = selectedFile.value
  if (!file) {
    ElMessage.warning(t('svcPanel.selectAudioFirst'))
    return
  }
  // Freeze before awaiting the settings flush. File changes during save/network
  // activity cannot relabel the submitted audio or change its request options.
  const svcSettings = configSnapshot()
  if (svcSettings.provider === 'disabled' || !svcSettings.base_url.trim()) {
    ElMessage.warning(svcReadinessMessage.value || t('svcPanel.waitingService'))
    return
  }
  isConverting.value = true
  resultAudioUrl.value = ''
  conversionError.value = ''
  const context = { requestId: crypto.randomUUID(), fileName: file.name, startedAt: new Date().toISOString(), config: svcSettings }
  conversionContext.value = context
  try {
    if (!(await runBeforeAction())) throw new Error(conversionError.value || t('svcPanel.saveFailed'))
    const saved = await settingsClient.load()
    if (unmounted) return
    if (!sameConfig(svcSettings, saved.svc) || !sameConfig(svcSettings, activeSvcConfig.value)) {
      throw new Error(t('svcPanel.saveFailed'))
    }
    const formData = new FormData()
    formData.append('file', file)
    formData.append('speaker_id', String(svcSettings.speaker_id))
    formData.append('pitch', String(svcSettings.pitch))
    const result = await requestJson<SvcConvertResponse>(`${API_ORIGIN}/svc/convert`, {
      method: 'POST', body: formData, headers: { 'x-trace-id': context.requestId },
      timeoutMs: conversionRequestTimeoutMs(svcSettings.timeout),
    })
    if (unmounted) return
    if (result.status === 'error') throw new Error(result.error || t('svcPanel.requestFailed', { status: 'error' }))
    const audioUrl = await normalizeAudioUrl(result.audio_url || result.url || '')
    if (unmounted) return
    if (!audioUrl) throw new Error(t('svcPanel.requestDoneNoAudio'))
    resultAudioUrl.value = audioUrl
    ElMessage.success(t('svcPanel.svcComplete'))
  } catch (error) {
    if (unmounted) return
    conversionError.value = describeFailure(error, t('svcPanel.serviceUnavailable'))
    ElMessage.error(conversionError.value)
  } finally {
    if (!unmounted) isConverting.value = false
  }
}

usePanelLifecycle(async () => {
  if (embedded.value) {
    Object.assign(voiceConfig.svc, settingsStore.state.svc)
    return
  }
  await loadSettings()
}, () => {
  settingsLoadSequence += 1
  serviceCheckSequence += 1
  svcCheckState.value = 'idle'
})

watch(() => settingsStore.state.svc, (value) => {
  if (unmounted) return
  Object.assign(voiceConfig.svc, value)
  svcCheckState.value = 'idle'
}, { deep: true })

watch(
  () => [
    embedded.value,
    activeSvcConfig.value.provider,
    activeSvcConfig.value.base_url,
    activeSvcConfig.value.speaker_id,
    activeSvcConfig.value.pitch,
    activeSvcConfig.value.timeout,
  ],
  () => {
    if (!unmounted) {
      serviceCheckSequence += 1
      svcCheckState.value = 'idle'
      svcCheckError.value = ''
    }
  },
)

onUnmounted(() => {
  unmounted = true
  settingsLoadSequence += 1
  serviceCheckSequence += 1
})
</script>

<style scoped>
.voice-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.svc-embedded-panel {
  display: block;
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

.conversion-context { overflow-wrap: anywhere; color: var(--yui-text-muted); }

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

<template>
  <slot v-if="showApplication" />
  <div v-else class="onboarding-page" :style="onboardingBackgroundStyle">
    <PanelShell
      class="onboarding-shell"
      minimal
      :title="t('onboarding.title')"
      :subtitle="t('onboarding.subtitle')"
    >
      <header class="onboarding-header drag">
        <div class="onboarding-heading">
          <span class="onboarding-kicker">{{ t('onboarding.kicker') }}</span>
          <h1>{{ t('onboarding.title') }}</h1>
          <p>{{ t('onboarding.subtitle') }}</p>
        </div>
        <div class="onboarding-header-actions no-drag">
          <el-select
            :model-value="currentLocale"
            class="language-select"
            :aria-label="t('language.select')"
            @change="changeLanguage"
          >
            <el-option v-for="locale in supportedLocales" :key="locale" :label="localeLabel(locale)" :value="locale" />
          </el-select>
          <el-button text @click="closeOnboarding">
            <el-icon><Close /></el-icon>{{ t(completed ? 'common.close' : 'onboarding.skipAndContinue') }}
          </el-button>
          <div v-if="isElectronPanel" class="window-actions" :aria-label="t('topbar.windowControls')">
            <button class="window-action" type="button" :title="t('topbar.minimize')" :aria-label="t('topbar.minimize')" @click="minimizeWindow">
              <el-icon><Minus /></el-icon>
            </button>
            <button class="window-action" type="button" :title="t('topbar.maximize')" :aria-label="t('topbar.maximize')" @click="maximizeWindow">
              <el-icon><FullScreen /></el-icon>
            </button>
            <button class="window-action danger" type="button" :title="t('topbar.close')" :aria-label="t('topbar.close')" @click="closeWindow">
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </div>
      </header>

      <AsyncState
        :loading="loading && !snapshot"
        :error="loadError"
        :empty="!snapshot && !loadError"
        :empty-text="t('onboarding.empty')"
        @retry="loadSnapshot"
      >
        <div v-if="snapshot" class="onboarding-content" aria-live="polite">
          <div class="onboarding-grid">
            <section class="readiness-section" aria-labelledby="readiness-title">
              <div class="section-heading">
                <div>
                  <h2 id="readiness-title">{{ t('onboarding.readiness.title') }}</h2>
                  <p>{{ readinessSummary }}</p>
                </div>
                <div class="readiness-heading-actions">
                  <span class="overall-status" :data-ready="snapshot.readyForText" role="status">
                    <el-icon v-if="snapshot.readyForText"><CircleCheckFilled /></el-icon>
                    <el-icon v-else><WarningFilled /></el-icon>
                    {{ snapshot.readyForText ? t('onboarding.textReady') : t('onboarding.textBlocked') }}
                  </span>
                  <el-button v-if="hiddenProbeCount" text size="small" @click="showAllProbes = !showAllProbes">
                    {{ t(showAllProbes ? 'onboarding.showRequired' : 'onboarding.showAll', { count: hiddenProbeCount }) }}
                  </el-button>
                </div>
              </div>

              <OnboardingReadinessRail :probes="visibleProbes" @repair="runRepair" />

              <div class="readiness-actions">
                <el-button
                  v-if="backendNeedsStart"
                  type="primary"
                  :loading="backendStartPending"
                  @click="startBackend"
                >
                  <el-icon><VideoPlay /></el-icon>{{ t('onboarding.backend.start') }}
                </el-button>
                <el-button v-if="runActive" plain :loading="action === 'cancel'" @click="cancelActiveOperation">
                  <el-icon><Close /></el-icon>{{ t(backendStartActive ? 'onboarding.backend.cancelStart' : 'onboarding.cancelChecks') }}
                </el-button>
                <el-button v-else-if="retryProbeIds.length" plain :loading="action === 'retry'" @click="retryFailed">
                  <el-icon><Refresh /></el-icon>{{ t('onboarding.retryFailed') }}
                </el-button>
              </div>
            </section>

            <div class="onboarding-side">
              <OnboardingModelSetup
                v-if="backendAvailable && !snapshot.readyForText"
                @completed="refreshModelReadiness"
              />

              <section class="optional-section" aria-labelledby="optional-title">
                <div class="section-heading">
                  <div>
                    <h2 id="optional-title">{{ t('onboarding.optional.title') }}</h2>
                    <p>{{ t('onboarding.optional.description') }}</p>
                  </div>
                  <el-button v-if="!optionalSkipped" text @click="optionalSkipped = true">{{ t('onboarding.optional.skip') }}</el-button>
                </div>

                <div v-if="optionalSkipped" class="optional-skipped" role="status">
                  <span>{{ t('onboarding.optional.skipped') }}</span>
                  <el-button text @click="optionalSkipped = false">{{ t('onboarding.optional.review') }}</el-button>
                </div>
                <div v-else class="optional-actions">
                  <el-button plain :loading="action === 'optional'" @click="runOptionalChecks">
                    <el-icon><Refresh /></el-icon>{{ t('onboarding.optional.check') }}
                  </el-button>
                  <el-button plain :loading="action === 'voice'" @click="runVoiceChecks">
                    <el-icon><Refresh /></el-icon>{{ t('onboarding.optional.voiceChain') }}
                  </el-button>
                  <el-button plain :loading="action === 'microphone'" @click="checkMicrophone">{{ t('onboarding.optional.microphone') }}</el-button>
                  <el-button plain :loading="action === 'speaker'" @click="checkSpeaker">{{ t('onboarding.optional.speaker') }}</el-button>
                  <span class="mcp-note"><el-icon><Lock /></el-icon>{{ t('onboarding.optional.mcpOff') }}</span>
                </div>
                <div v-if="deviceResults.microphone || deviceResults.speaker" class="device-results" role="status" aria-live="polite">
                  <span v-if="deviceResults.microphone">{{ deviceResults.microphone }}</span>
                  <span v-if="deviceResults.speaker">{{ deviceResults.speaker }}</span>
                </div>
              </section>
            </div>
          </div>

          <footer class="onboarding-footer">
            <p v-if="actionError" role="alert">{{ actionError }}</p>
            <el-button plain @click="continueWithoutSetup">
              {{ t(snapshot.readyForText ? 'onboarding.closeCheck' : 'onboarding.skipAndContinue') }}
            </el-button>
            <el-button type="primary" :disabled="!snapshot.readyForText" @click="startChatting">
              <el-icon><ChatDotRound /></el-icon>{{ t('onboarding.startChatting') }}
            </el-button>
          </footer>
        </div>
      </AsyncState>
    </PanelShell>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChatDotRound, CircleCheckFilled, Close, FullScreen, Lock, Minus, Refresh, VideoPlay, WarningFilled } from '@element-plus/icons-vue'
import type { OnboardingDeviceProbeReport, OnboardingProbeId, OnboardingReadinessSnapshot, OnboardingRepairActionId } from '@/../shared/onboarding-readiness'
import { currentLocale, localeLabel, setLocale, supportedLocales, t } from '@/i18n'
import { yuizakiConfig } from '@/config/yuizaki'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import OnboardingModelSetup from '../components/OnboardingModelSetup.vue'
import OnboardingReadinessRail from '../components/OnboardingReadinessRail.vue'
import { ONBOARDING_OPEN_EVENT } from '../onboardingEvents'
import { enumerateAudioDevices } from '@/audio/audio-capture'

const COMPLETION_KEY = 'yuizaki.onboarding.completed.v1'
const OPTIONAL_PROBES: OnboardingProbeId[] = ['tts.status', 'asr.runtime', 'database.status', 'memory.status', 'host.avatar']

const snapshot = ref<OnboardingReadinessSnapshot | null>(null)
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const action = ref<'backend' | 'cancel' | 'retry' | 'optional' | 'voice' | 'microphone' | 'speaker' | ''>('')
const optionalSkipped = ref(false)
const showAllProbes = ref(false)
const deviceResults = ref({ microphone: '', speaker: '' })
const reopened = ref(false)
const completed = ref(window.localStorage.getItem(COMPLETION_KEY) === 'true')
const backendStartPending = ref(false)
let pollTimer: ReturnType<typeof window.setTimeout> | null = null
let backendStartGeneration = 0
let emptyIdlePollCount = 0
const MAX_EMPTY_IDLE_POLLS = 10

const onboardingBackgroundStyle = computed(() => ({
  '--onboarding-wallpaper': yuizakiConfig.slides[0] ? `url("${yuizakiConfig.slides[0]}")` : 'none',
}))

const onboardingApi = computed(() => window.petApi?.onboarding)
const isElectronPanel = computed(() => Boolean(window.petApi?.window))
const trustedE2EActivation = computed(() => Boolean(window.petApi?.e2e))
const showApplication = computed(() => trustedE2EActivation.value || !onboardingApi.value || (completed.value && !reopened.value))
const backendStartActive = computed(() => snapshot.value?.operation === 'backend_start' ||
  (snapshot.value?.operation !== 'probe_scan' && backendStartPending.value))
const runActive = computed(() => backendStartActive.value ||
  snapshot.value?.operation === 'backend_start' || snapshot.value?.operation === 'probe_scan')
const backendProbe = computed(() => snapshot.value?.probes.find(probe => probe.id === 'backend.service'))
const backendAvailable = computed(() => backendProbe.value?.status === 'ready')
const backendNeedsStart = computed(() => snapshot.value?.operation === 'idle' && (
  !backendProbe.value || ['failed', 'needs_user', 'cancelled'].includes(backendProbe.value.status)
))
const retryProbeIds = computed<OnboardingProbeId[]>(() => snapshot.value?.probes
  .filter(probe => ['failed', 'degraded', 'unavailable', 'cancelled', 'needs_user'].includes(probe.status))
  .map(probe => probe.id) ?? [])
const unresolvedProbe = (probe: OnboardingReadinessSnapshot['probes'][number]): boolean => (
  ['degraded', 'unavailable', 'failed', 'cancelled', 'needs_user', 'running', 'pending'].includes(probe.status)
)
const visibleProbes = computed(() => {
  const probes = snapshot.value?.probes ?? []
  if (showAllProbes.value) return probes
  const unresolved = probes.filter(unresolvedProbe)
  if (unresolved.length) return unresolved
  return probes.filter(probe => probe.requiredForText)
})
const hiddenProbeCount = computed(() => Math.max(0, (snapshot.value?.probes.length ?? 0) - visibleProbes.value.length))
const readinessSummary = computed(() => snapshot.value?.readyForText
  ? t('onboarding.readiness.readySummary')
  : t('onboarding.readiness.blockedSummary'))

const messageFrom = (cause: unknown, fallback: string): string => cause instanceof Error ? cause.message : fallback

const schedulePoll = (): void => {
  const waitingForInitialState = snapshot.value?.operation === 'idle' &&
    snapshot.value.probes.length === 0 && emptyIdlePollCount < MAX_EMPTY_IDLE_POLLS
  if ((!runActive.value && !waitingForInitialState) || pollTimer !== null) return
  pollTimer = window.setTimeout(async () => {
    pollTimer = null
    await loadSnapshot(false)
  }, 900)
}

const applySnapshot = (next: OnboardingReadinessSnapshot): void => {
  snapshot.value = next
  if (next.operation === 'idle' && next.probes.length === 0) emptyIdlePollCount += 1
  schedulePoll()
}

const loadSnapshot = async (showLoading = true): Promise<void> => {
  const api = onboardingApi.value
  if (!api) return
  if (showLoading) loading.value = true
  loadError.value = ''
  try {
    applySnapshot(await api.snapshot())
  } catch (cause) {
    loadError.value = messageFrom(cause, t('onboarding.loadFailed'))
  } finally {
    loading.value = false
  }
}

const runAction = async (
  name: typeof action.value,
  operation: () => Promise<OnboardingReadinessSnapshot>,
): Promise<void> => {
  if (action.value) return
  action.value = name
  actionError.value = ''
  try {
    applySnapshot(await operation())
  } catch (cause) {
    actionError.value = messageFrom(cause, t('onboarding.actionFailed'))
  } finally {
    action.value = ''
  }
}

const startBackend = (): void => {
  if (backendStartPending.value || action.value) return
  const api = onboardingApi.value
  if (!api) return
  const generation = ++backendStartGeneration
  backendStartPending.value = true
  actionError.value = ''
  schedulePoll()
  void api.startBackend()
    .then((next) => {
      if (generation === backendStartGeneration) applySnapshot(next)
    })
    .catch((cause) => {
      if (generation === backendStartGeneration) actionError.value = messageFrom(cause, t('onboarding.actionFailed'))
    })
    .finally(() => {
      if (generation === backendStartGeneration) backendStartPending.value = false
    })
}
const cancelActiveOperation = async (): Promise<void> => {
  if (action.value === 'cancel') return
  const api = onboardingApi.value
  if (!api) return
  const runId = snapshot.value?.runId
  backendStartGeneration += 1
  action.value = 'cancel'
  actionError.value = ''
  try {
    const next = backendStartActive.value
      ? await api.cancelBackend()
      : runId
        ? await api.cancelRun({ runId })
        : null
    if (next) applySnapshot(next)
  } catch (cause) {
    actionError.value = messageFrom(cause, t('onboarding.actionFailed'))
  } finally {
    backendStartPending.value = false
    action.value = ''
  }
}
const retryFailed = (): Promise<void> => {
  const current = snapshot.value
  if (!current) return Promise.resolve()
  return runAction('retry', () => onboardingApi.value!.retry({ runId: current.runId, probeIds: retryProbeIds.value }))
}
const refreshModelReadiness = (): Promise<void> => runAction('retry', () => onboardingApi.value!.runProbe({
  probeIds: ['llm.provider', 'llm.model_chat'],
}))
const runOptionalChecks = (): Promise<void> => runAction('optional', () => onboardingApi.value!.runProbe({ probeIds: OPTIONAL_PROBES }))
const runVoiceChecks = (): Promise<void> => runAction('voice', () => onboardingApi.value!.runProbe({
  probeIds: ['llm.provider', 'llm.model_chat', 'tts.status', 'asr.runtime'],
}))
const runRepair = (actionId: OnboardingRepairActionId): Promise<void> => {
  // Navigation repairs need the app shell visible before the destination route can render.
  if (actionId.startsWith('navigate:')) continueWithoutSetup()
  return runAction('retry', () => onboardingApi.value!.runRepair({ actionId }))
}

const reportDeviceResult = async (report: OnboardingDeviceProbeReport): Promise<void> => {
  try {
    applySnapshot(await onboardingApi.value!.reportDeviceProbe(report))
  } catch (cause) {
    actionError.value = messageFrom(cause, t('onboarding.actionFailed'))
  }
}

const microphoneFailureCode = (cause: unknown): OnboardingDeviceProbeReport['messageCode'] => {
  if (cause instanceof DOMException) {
    if (cause.name === 'NotAllowedError' || cause.name === 'SecurityError') return 'permission_denied'
    if (cause.name === 'NotFoundError' || cause.name === 'OverconstrainedError') return 'no_device'
  }
  return 'test_failed'
}

const checkMicrophone = async (): Promise<void> => {
  if (action.value) return
  action.value = 'microphone'
  deviceResults.value.microphone = ''
  let stream: MediaStream | null = null
  let report: OnboardingDeviceProbeReport = {
    probeId: 'host.microphone',
    outcome: 'unavailable',
    messageCode: 'test_failed',
  }
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      report = { probeId: 'host.microphone', outcome: 'unavailable', messageCode: 'no_device' }
      throw new Error(t('onboarding.optional.microphoneUnsupported'))
    }
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const inventory = await enumerateAudioDevices().catch(() => null)
    deviceResults.value.microphone = inventory && inventory.inputCount > 0
      ? `${t('onboarding.optional.microphonePassed')}（检测到 ${inventory.inputCount} 个输入设备）`
      : t('onboarding.optional.microphonePassed')
    report = { probeId: 'host.microphone', outcome: 'ready', messageCode: 'permission_granted' }
  } catch (cause) {
    if (report.messageCode !== 'no_device') {
      report = { probeId: 'host.microphone', outcome: 'unavailable', messageCode: microphoneFailureCode(cause) }
    }
    deviceResults.value.microphone = t('onboarding.optional.microphoneFailed', {
      message: messageFrom(cause, t('common.error.unknown')),
    })
  } finally {
    stream?.getTracks().forEach(track => track.stop())
  }
  await reportDeviceResult(report)
  action.value = ''
}

const checkSpeaker = async (): Promise<void> => {
  if (action.value) return
  action.value = 'speaker'
  deviceResults.value.speaker = ''
  let context: AudioContext | null = null
  let report: OnboardingDeviceProbeReport = {
    probeId: 'host.speaker',
    outcome: 'unavailable',
    messageCode: 'test_failed',
  }
  try {
    context = new AudioContext()
    await context.resume()
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.frequency.value = 440
    gain.gain.value = 0.035
    oscillator.connect(gain)
    gain.connect(context.destination)
    const finished = new Promise<void>(resolve => { oscillator.onended = () => resolve() })
    oscillator.start()
    oscillator.stop(context.currentTime + 0.18)
    await finished
    const inventory = await enumerateAudioDevices().catch(() => null)
    deviceResults.value.speaker = inventory && inventory.outputCount > 0
      ? `${t('onboarding.optional.speakerPlayed')}（检测到 ${inventory.outputCount} 个输出设备）`
      : t('onboarding.optional.speakerPlayed')
    report = { probeId: 'host.speaker', outcome: 'ready', messageCode: 'test_completed' }
  } catch (cause) {
    deviceResults.value.speaker = t('onboarding.optional.speakerFailed', {
      message: messageFrom(cause, t('common.error.unknown')),
    })
  } finally {
    if (context && context.state !== 'closed') await context.close().catch(() => undefined)
  }
  await reportDeviceResult(report)
  action.value = ''
}

const changeLanguage = async (value: string): Promise<void> => {
  actionError.value = ''
  try {
    await setLocale(value, { persistSettings: backendAvailable.value })
  } catch (cause) {
    actionError.value = messageFrom(cause, t('onboarding.actionFailed'))
  }
}

const startChatting = (): void => {
  if (!snapshot.value?.readyForText) return
  continueWithoutSetup()
}

const continueWithoutSetup = (): void => {
  window.localStorage.setItem(COMPLETION_KEY, 'true')
  completed.value = true
  reopened.value = false
}
const closeOnboarding = (): void => continueWithoutSetup()
const minimizeWindow = (): void => { void window.petApi?.window?.minimize() }
const maximizeWindow = (): void => { void window.petApi?.window?.maximize() }
const closeWindow = (): void => { void window.petApi?.window?.close() }
const handleOpen = (): void => {
  reopened.value = true
  optionalSkipped.value = false
  showAllProbes.value = false
  void loadSnapshot()
}

onMounted(() => {
  window.addEventListener(ONBOARDING_OPEN_EVENT, handleOpen)
  if (!showApplication.value) void loadSnapshot()
})

onBeforeUnmount(() => {
  window.removeEventListener(ONBOARDING_OPEN_EVENT, handleOpen)
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})
</script>

<style scoped>
.onboarding-page {
  position: relative;
  isolation: isolate;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  overflow: auto;
  padding: 20px 28px;
  background: var(--yui-app-bg, #edf2f7);
  color: var(--yui-text, #172033);
}

.onboarding-page::before,
.onboarding-page::after {
  position: fixed;
  inset: 0;
  pointer-events: none;
  content: '';
}

.onboarding-page::before {
  z-index: -2;
  background-image: var(--onboarding-wallpaper);
  background-position: center;
  background-size: cover;
  opacity: 0.24;
}

.onboarding-page::after {
  z-index: -1;
  background: color-mix(in srgb, var(--yui-app-bg, #edf2f7) 76%, transparent);
}

.onboarding-shell {
  position: relative;
  z-index: 1;
  width: min(1120px, 100%);
  min-height: 100%;
  margin: 0 auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.onboarding-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}

.onboarding-heading { min-width: 0; }
.onboarding-kicker { color: var(--yui-accent); font-size: 12px; font-weight: 700; }
.onboarding-heading h1 { margin: 4px 0 0; color: var(--yui-text, #172033); font-size: 22px; line-height: 1.25; }
.onboarding-heading p { max-width: 70ch; margin: 6px 0 0; color: var(--yui-muted, #526176); font-size: 13px; line-height: 1.5; }
.onboarding-header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.language-select { width: 132px; }
.window-actions { display: inline-flex; align-items: center; gap: 4px; }
.window-action {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--yui-border, #d9e1ea);
  border-radius: 8px;
  color: var(--yui-muted, #64748b);
  background: transparent;
  cursor: pointer;
  transition: color 150ms ease, background 150ms ease, border-color 150ms ease;
}
.window-action:hover, .window-action:focus-visible { border-color: var(--yui-border-strong, #94a3b8); color: var(--yui-accent); background: var(--yui-accent-soft, #eff6ff); }
.window-action.danger:hover, .window-action.danger:focus-visible { border-color: #fda4af; color: #e11d48; background: var(--yui-danger-soft, #fff1f2); }
.window-action:focus-visible { outline: 2px solid var(--yui-accent); outline-offset: 2px; }
.onboarding-content { display: flex; flex-direction: column; gap: 20px; }
.readiness-section, .optional-section { min-width: 0; }

.onboarding-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); gap: 28px; align-items: start; }
.onboarding-side { display: grid; min-width: 0; gap: 22px; }

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.readiness-heading-actions { display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: 4px; }

.section-heading h2 { margin: 0; color: var(--yui-text, #172033); font-size: 16px; line-height: 1.35; }
.section-heading p { max-width: 65ch; margin: 4px 0 0; color: var(--yui-text-muted, #526176); font-size: 13px; line-height: 1.5; }

.overall-status {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  color: #a16207;
  font-size: 13px;
  font-weight: 650;
}
.overall-status[data-ready='true'] { color: #15803d; }

.readiness-actions, .optional-actions, .onboarding-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.readiness-actions { margin-top: 8px; padding-left: 36px; }
.optional-section { padding-top: 0; }
.optional-skipped { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--yui-text-muted, #526176); font-size: 13px; }
.mcp-note { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; color: var(--yui-text-muted, #526176); font-size: 12px; }
.device-results { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; color: var(--yui-text-muted, #526176); font-size: 12px; }

.onboarding-footer {
  justify-content: flex-end;
  padding-top: 20px;
}
.onboarding-footer { gap: 10px; }
.onboarding-footer p { flex: 1 1 100%; margin: 0; overflow-wrap: anywhere; color: #b91c1c; font-size: 13px; }

@media (max-width: 760px) {
  .onboarding-page { padding: 16px; }
  .onboarding-shell { min-height: 100%; }
  .onboarding-grid { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 520px) {
  .onboarding-page { padding: 0; }
  .onboarding-header { flex-direction: column; }
  .onboarding-header-actions { width: 100%; justify-content: space-between; }
  .window-actions { margin-left: auto; }
  .section-heading { align-items: stretch; flex-direction: column; }
  .overall-status { align-self: flex-start; }
  .readiness-heading-actions { align-items: flex-start; }
  .readiness-actions { padding-left: 0; }
  .readiness-actions :deep(.el-button), .optional-actions :deep(.el-button) { flex: 1 1 100%; margin-left: 0; }
  .mcp-note { width: 100%; margin: 4px 0 0; }
  .onboarding-footer :deep(.el-button) { flex: 1 1 auto; margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .onboarding-page, .onboarding-page * { scroll-behavior: auto; transition-duration: 0.01ms !important; }
}
</style>

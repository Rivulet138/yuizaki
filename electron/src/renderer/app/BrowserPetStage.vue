<template>
  <div class="browser-pet-stage" :data-model-type="modelType" :data-fit-scale="fittedScale" :aria-label="t('browserPet.modelAriaLabel', { model: modelLabel })">
    <img v-if="!ready && modelType === 'live2d'" class="browser-pet-fallback" :src="fallbackImageUrl" alt="" />
    <div
      ref="mountEl"
      class="browser-pet-canvas"
      :class="{ 'is-ready': ready }"
      :style="{ '--browser-model-scale': zoomScale }"
      aria-hidden="true"
    ></div>
    <div v-if="loading" class="browser-pet-status">{{ t('browserPet.loading', { model: modelLabel }) }}</div>
    <button v-else-if="error" type="button" class="browser-pet-status browser-pet-status--error" @click="refreshModel">{{ t('browserPet.unavailable', { model: modelLabel }) }} · {{ t('shell.retry') }}</button>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import type { PetRenderer as PetRendererInstance } from '@/pet-renderer'
import { petControl } from '@/utils/petControl'
import type {
  PetControlDirective,
  PetLipSyncLevelPayload,
  PetLipSyncVisemePayload,
  PetModelDefinition,
  PetModelType,
} from '@/../shared/pet-control'
import type { AvatarCommand } from '@/../shared/avatar-command'
import { resolveBackendUrl } from '@/api/clients/http-client'
import { t } from '@/i18n'

const fallbackImageUrl = '/live2d/llm-live2d/yumi/yumi-stage.png'
const mountEl = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref(false)
const ready = ref(false)
const modelType = ref<PetModelType>('live2d')
const modelLabel = ref('Live2D')
const browserInteractMode = ref(false)
const browserLocked = ref(false)
const zoomBounds = { min: 0.7, max: 1.8 }
const zoomScale = ref(1)
const fittedScale = ref(1)
const emit = defineEmits<{ 'zoom-change': [scale: number] }>()
let renderer: PetRendererInstance | null = null
let resizeObserver: ResizeObserver | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let fitTimer: ReturnType<typeof setTimeout> | null = null
let currentModelKey = ''
let pendingModelKey = ''
let modelGeneration = 0
let disposed = false
let active = false
let stageActivated = false
let refreshing = false
let refreshGeneration = 0
let pendingRenderer: PetRendererInstance | null = null
let pendingMount: HTMLElement | null = null
let activeMount: HTMLElement | null = null
let ttsPlaybackToken = 0
let ttsGenerationId: string | undefined

const fitModelToViewport = (): void => {
  fitTimer = null
  if (!active || disposed) return
  const fit = renderer?.fitEmbeddedModelToViewport()
  if (fit != null) fittedScale.value = fit
}
const scheduleModelFit = (): void => {
  if (fitTimer) clearTimeout(fitTimer)
  fitTimer = null
  if (!active || disposed) return
  fitTimer = setTimeout(fitModelToViewport, 200)
}

const modelAssetUrl = (model: PetModelDefinition | undefined): string => {
  if (!model?.assetPath) return '/live2d/llm-live2d/yumi/yumi.model3.json'
  if (model.assetPath.startsWith('/')) return model.assetPath
  const kind = model.type === 'vrm' ? 'vrm' : 'live2d'
  return `/${kind}/${model.assetPath.split('/').map((part) => encodeURIComponent(part)).join('/')}`
}

const adjustZoom = (delta: number): void => {
  zoomScale.value = Number(Math.max(zoomBounds.min, Math.min(zoomBounds.max, zoomScale.value + delta)).toFixed(2))
  emit('zoom-change', zoomScale.value)
}

const resetZoom = (): void => {
  zoomScale.value = 1
  emit('zoom-change', zoomScale.value)
}

const handleInputAction = (event: Event): void => {
  if (!active) return
  const action = (event as CustomEvent<{ action?: string }>).detail?.action
  if (action === 'interact') browserInteractMode.value = !browserInteractMode.value
  if (action === 'lock') browserLocked.value = !browserLocked.value
  if (!renderer || (action !== 'interact' && action !== 'lock')) return
  void renderer.applyBrowserConfig({
    interactMode: browserInteractMode.value,
    locked: browserLocked.value,
    clickThrough: false,
  })
}

interface BrowserPetControlPayload {
  avatar_command?: unknown
  petLinkEnabled?: boolean
  expression_name?: string
  expression_mix?: Array<{ expression?: unknown; weight?: unknown }>
  expressionMix?: Array<{ expression?: unknown; weight?: unknown }>
  parameter_overrides?: Array<{ id?: unknown; value?: unknown; weight?: unknown }>
  parameterOverrides?: Array<{ id?: unknown; value?: unknown; weight?: unknown }>
  motion?: { group?: unknown; index?: unknown }
  motion_group?: string
  motion_index?: number
  intensity?: number
  duration_ms?: number
  durationMs?: number
}

const normalizeExpressionMix = (payload: BrowserPetControlPayload) => {
  const raw = Array.isArray(payload.expression_mix)
    ? payload.expression_mix
    : Array.isArray(payload.expressionMix)
      ? payload.expressionMix
      : []
  const items = raw.flatMap((item) => (
    typeof item?.expression === 'string' && item.expression.trim()
      ? [{
          expression: item.expression.trim(),
          weight: typeof item.weight === 'number' && Number.isFinite(item.weight)
            ? item.weight
            : 1,
        }]
      : []
  ))
  if (
    items.length === 0
    && typeof payload.expression_name === 'string'
    && payload.expression_name.trim()
  ) {
    items.push({
      expression: payload.expression_name.trim(),
      weight: typeof payload.intensity === 'number' && Number.isFinite(payload.intensity)
        ? payload.intensity
        : 1,
    })
  }
  return items
}

const normalizeParameterOverrides = (payload: BrowserPetControlPayload) => {
  const raw = Array.isArray(payload.parameter_overrides)
    ? payload.parameter_overrides
    : Array.isArray(payload.parameterOverrides)
      ? payload.parameterOverrides
      : []
  return raw.flatMap((item) => (
    typeof item?.id === 'string'
    && item.id.trim()
    && typeof item.value === 'number'
    && Number.isFinite(item.value)
      ? [{
          id: item.id.trim(),
          value: item.value,
          ...(typeof item.weight === 'number' && Number.isFinite(item.weight)
            ? { weight: item.weight }
            : {}),
        }]
      : []
  ))
}

const handleLlmControl = (event: Event): void => {
  if (!renderer) return
  const payload = (event as CustomEvent<BrowserPetControlPayload>).detail
  if (!payload || typeof payload !== 'object' || payload.petLinkEnabled === false) return

  if (payload.avatar_command && typeof payload.avatar_command === 'object') {
    renderer.applyAvatarCommand(payload.avatar_command as AvatarCommand)
    return
  }

  const expressionMix = normalizeExpressionMix(payload)
  const parameterOverrides = normalizeParameterOverrides(payload)
  const motionGroup = typeof payload.motion?.group === 'string'
    ? payload.motion.group.trim()
    : typeof payload.motion_group === 'string'
      ? payload.motion_group.trim()
      : ''
  const rawMotionIndex = payload.motion?.index ?? payload.motion_index
  const motionIndex = typeof rawMotionIndex === 'number' && Number.isFinite(rawMotionIndex)
    ? rawMotionIndex
    : 0
  if (expressionMix.length === 0 && parameterOverrides.length === 0 && !motionGroup) return

  const directive: PetControlDirective = {
    expressionMix,
    parameterOverrides,
    ...(motionGroup ? { motion: { group: motionGroup, index: motionIndex } } : {}),
    intensity: typeof payload.intensity === 'number' && Number.isFinite(payload.intensity)
      ? payload.intensity
      : 1,
    durationMs: typeof payload.duration_ms === 'number' && Number.isFinite(payload.duration_ms)
      ? payload.duration_ms
      : typeof payload.durationMs === 'number' && Number.isFinite(payload.durationMs)
        ? payload.durationMs
        : 1800,
  }
  renderer.applyPetControlDirective(directive)
}

const shouldDriveEmbeddedLipSync = (): boolean => false

const handleTtsPlayUrl = (event: Event): void => {
  if (!renderer || shouldDriveEmbeddedLipSync()) return
  const detail = (event as CustomEvent<{
    audio_url?: unknown
    generationId?: string
    petLinkEnabled?: unknown
  }>).detail
  if (detail?.petLinkEnabled === false) return
  const audioUrl = typeof detail?.audio_url === 'string' ? detail.audio_url.trim() : ''
  if (!audioUrl) return
  const targetRenderer = renderer
  ttsGenerationId = detail?.generationId
  const token = ++ttsPlaybackToken
  void resolveBackendUrl(audioUrl)
    .then((resolvedUrl) => {
      if (disposed || !active || renderer !== targetRenderer || token !== ttsPlaybackToken) return
      return targetRenderer.startLipSync(resolvedUrl)
    })
    .catch((error: unknown) => {
      console.debug('[BrowserPetStage] failed to start lip sync:', error)
    })
}

const handleTtsStop = (event: Event): void => {
  ttsPlaybackToken += 1
  ttsGenerationId = undefined
  const detail = (event as CustomEvent<{ interrupted?: unknown }>).detail
  renderer?.stopLipSync({ interrupted: detail?.interrupted === true })
}

const handleAudioStarted = (event: Event): void => {
  const generationId = (event as CustomEvent<{ generationId?: string }>).detail?.generationId
  if (generationId !== ttsGenerationId) ttsPlaybackToken += 1
  ttsGenerationId = generationId
}

const handleAudioEnded = (event: Event): void => {
  const generationId = (event as CustomEvent<{ generationId?: string }>).detail?.generationId
  if (generationId && generationId !== ttsGenerationId) return
  ttsPlaybackToken += 1
  ttsGenerationId = undefined
  renderer?.stopLipSync()
}

const handleLipSyncLevel = (event: Event): void => {
  if (!renderer || shouldDriveEmbeddedLipSync()) return
  const detail = (event as CustomEvent<PetLipSyncLevelPayload>).detail
  if (!detail || typeof detail !== 'object') return
  renderer.setExternalLipSync(detail)
}

const handleLipSyncViseme = (event: Event): void => {
  if (!renderer || shouldDriveEmbeddedLipSync()) return
  const detail = (event as CustomEvent<PetLipSyncVisemePayload>).detail
  if (!detail || typeof detail !== 'object') return
  renderer.setExternalViseme(detail)
}

defineExpose({ adjustZoom, resetZoom, zoomScale, zoomBounds })

// Load into a separate mount so a failed replacement leaves the working model intact.
const loadModel = async (model: PetModelDefinition | undefined): Promise<void> => {
  const nextType = model?.type || 'live2d'
  const nextPath = modelAssetUrl(model)
  const nextKey = `${nextType}:${model?.id || 'yumi'}:${nextPath}`
  if (disposed || !active || document.hidden || nextKey === pendingModelKey) return
  if (nextKey === currentModelKey) {
    if (pendingModelKey) {
      modelGeneration += 1
      pendingRenderer?.destroy()
      pendingRenderer = null
      pendingMount?.remove()
      pendingMount = null
      pendingModelKey = ''
    }
    loading.value = false
    error.value = false
    return
  }
  const generation = ++modelGeneration
  const isCurrent = () => !disposed && active && !document.hidden && generation === modelGeneration
  pendingRenderer?.destroy()
  pendingMount?.remove()
  pendingRenderer = null
  pendingMount = null
  pendingModelKey = nextKey
  loading.value = true
  error.value = false
  let candidate: PetRendererInstance | null = null
  let candidateMount: HTMLElement | null = null
  try {
    const { ensureCubismCore } = await import('@/pet-renderer-core')
    if (!isCurrent()) return
    if (nextType === 'live2d') await ensureCubismCore()
    if (!isCurrent()) return
    const { PetRenderer } = await import('@/pet-renderer')
    if (!isCurrent() || !mountEl.value) return
    candidateMount = document.createElement('div')
    candidateMount.id = `browser-pet-stage-${generation}-${Math.random().toString(36).slice(2)}`
    Object.assign(candidateMount.style, { position: 'absolute', inset: '0', visibility: 'hidden', pointerEvents: 'none' })
    mountEl.value.appendChild(candidateMount)
    pendingMount = candidateMount
    candidate = new PetRenderer(candidateMount.id)
    pendingRenderer = candidate
    candidate.setEmbeddedActive(active)
    await candidate.init()
    if (!isCurrent()) return
    const rect = mountEl.value?.getBoundingClientRect()
    if (rect && rect.width > 0 && rect.height > 0) candidate.resizeTo(rect.width, rect.height)
    await candidate.applyBrowserConfig({
      modelType: nextType,
      modelId: model?.id || 'yumi',
      modelPath: nextPath,
      emotionPresets: model?.emotions ?? [],
      scale: nextType === 'vrm' ? 0.96 : 0.9,
      clickThrough: false,
      locked: browserLocked.value,
      interactMode: browserInteractMode.value,
      opacity: 1,
      placement: 'center',
    })
    if (!isCurrent()) return
    // Input actions can change while assets are loading.
    await candidate.applyBrowserConfig({ locked: browserLocked.value, interactMode: browserInteractMode.value })
    if (!isCurrent()) return
    ttsPlaybackToken += 1
    ttsGenerationId = undefined
    renderer?.destroy()
    activeMount?.remove()
    renderer = candidate
    activeMount = candidateMount
    candidateMount.style.visibility = 'visible'
    candidateMount.style.pointerEvents = ''
    pendingRenderer = null
    pendingMount = null
    currentModelKey = nextKey
    modelType.value = nextType
    modelLabel.value = nextType === 'vrm' ? 'VRM' : 'Live2D'
    fittedScale.value = 1
    ready.value = true
    scheduleModelFit()
  } catch (cause) {
    if (isCurrent()) {
      console.warn('[BrowserPetStage] model load failed', cause)
      error.value = true
    }
  } finally {
    if (renderer !== candidate) {
      candidate?.destroy()
      candidateMount?.remove()
    }
    if (isCurrent()) {
      pendingRenderer = null
      pendingMount = null
      pendingModelKey = ''
      loading.value = false
    }
  }
}

const refreshModel = async (): Promise<void> => {
  if (disposed || !active || document.hidden || refreshing) return
  refreshing = true
  const generation = ++refreshGeneration
  const isCurrent = () => !disposed && active && !document.hidden && generation === refreshGeneration
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  try {
    const [state, catalog] = await Promise.all([petControl.getState(), petControl.getCatalog()])
    if (!isCurrent()) return
    const model = catalog.models.find((item) => item.id === (state.modelId || catalog.activeModelId)) || catalog.models[0]
    void loadModel(model)
  } catch (cause) {
    if (!isCurrent()) return
    console.warn('[BrowserPetStage] model catalog unavailable', cause)
    if (!currentModelKey && !pendingModelKey) void loadModel(undefined)
    else if (!pendingModelKey) error.value = true
  } finally {
    if (generation === refreshGeneration) {
      refreshing = false
      if (!disposed && active && !document.hidden) refreshTimer = setTimeout(refreshModel, 2500)
    }
  }
}

const resizeStage = (): void => {
  if (!active || disposed) return
  const rect = mountEl.value?.getBoundingClientRect()
  if (rect && rect.width > 0 && rect.height > 0) {
    renderer?.resizeTo(rect.width, rect.height)
    pendingRenderer?.resizeTo(rect.width, rect.height)
    scheduleModelFit()
  }
}

const activateStage = (): void => {
  if (active || disposed || !stageActivated || document.hidden || !mountEl.value) return
  active = true
  window.addEventListener('yuizaki:input-action', handleInputAction)
  window.addEventListener('pet:llm-control', handleLlmControl)
  window.addEventListener('pet:tts-play-url', handleTtsPlayUrl)
  window.addEventListener('pet:tts-stop', handleTtsStop)
  window.addEventListener('pet:audio-started', handleAudioStarted)
  window.addEventListener('pet:audio-ended', handleAudioEnded)
  window.addEventListener('pet:lipsync-level', handleLipSyncLevel)
  window.addEventListener('pet:lipsync-viseme', handleLipSyncViseme)
  renderer?.setEmbeddedActive(true)
  resizeObserver?.observe(mountEl.value)
  void nextTick(resizeStage)
  void refreshModel()
}

const deactivateStage = (): void => {
  if (!active) return
  active = false
  refreshGeneration += 1
  refreshing = false
  modelGeneration += 1
  ttsPlaybackToken += 1
  ttsGenerationId = undefined
  renderer?.stopLipSync()
  renderer?.setEmbeddedActive(false)
  pendingRenderer?.setEmbeddedActive(false)
  pendingRenderer?.destroy()
  pendingRenderer = null
  pendingMount?.remove()
  pendingMount = null
  pendingModelKey = ''
  loading.value = false
  window.removeEventListener('yuizaki:input-action', handleInputAction)
  window.removeEventListener('pet:llm-control', handleLlmControl)
  window.removeEventListener('pet:tts-play-url', handleTtsPlayUrl)
  window.removeEventListener('pet:tts-stop', handleTtsStop)
  window.removeEventListener('pet:audio-started', handleAudioStarted)
  window.removeEventListener('pet:audio-ended', handleAudioEnded)
  window.removeEventListener('pet:lipsync-level', handleLipSyncLevel)
  window.removeEventListener('pet:lipsync-viseme', handleLipSyncViseme)
  if (fitTimer) clearTimeout(fitTimer)
  fitTimer = null
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  resizeObserver?.disconnect()
}

// KeepAlive activation and document visibility can resume in either order.
// The active guard owns the single refresh/polling chain for both hooks.
const handleVisibilityChange = (): void => {
  if (document.hidden) deactivateStage()
  else activateStage()
}

const resumeStage = (): void => {
  stageActivated = true
  activateStage()
}

onMounted(() => {
  emit('zoom-change', zoomScale.value)
  resizeObserver = new ResizeObserver(resizeStage)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  resumeStage()
})
onActivated(resumeStage)
onDeactivated(() => {
  stageActivated = false
  deactivateStage()
})
onBeforeUnmount(() => {
  disposed = true
  stageActivated = false
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  deactivateStage()
  resizeObserver = null
  renderer?.destroy()
  renderer = null
  activeMount?.remove()
  activeMount = null
})
</script>

<style scoped>
.browser-pet-stage {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  margin: 0 auto;
}

.browser-pet-canvas,
.browser-pet-fallback {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.browser-pet-canvas { z-index: 1; }

.browser-pet-canvas :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}

.browser-pet-canvas.is-ready :deep(canvas) {
  transform: scale(var(--browser-model-scale, 1));
  transform-origin: center center;
}

.browser-pet-fallback {
  object-fit: contain;
  object-position: center bottom;
  box-sizing: border-box;
  padding: 24px 12px;
  transform-origin: center center;
  filter: drop-shadow(0 28px 30px rgba(39, 49, 84, 0.25));
}

.browser-pet-status {
  position: absolute;
  left: 50%;
  bottom: 10%;
  transform: translateX(-50%);
  padding: 5px 10px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  color: #475569;
  font-size: 12px;
  white-space: nowrap;
}

.browser-pet-status--error {
  color: #7c3aed;
}

</style>

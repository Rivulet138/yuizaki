<template>
  <div class="browser-pet-stage" :data-model-type="modelType" :aria-label="t('browserPet.modelAriaLabel', { model: modelLabel })">
    <img v-if="!ready && modelType === 'live2d'" class="browser-pet-fallback" src="/live2d/llm-live2d/yumi/yumi-stage.png" alt="" />
    <div
      ref="mountEl"
      class="browser-pet-canvas"
      :class="{ 'is-ready': ready }"
      :style="{ '--browser-model-scale': zoomScale }"
      aria-hidden="true"
    ></div>
    <div v-if="loading" class="browser-pet-status">{{ t('browserPet.loading', { model: modelLabel }) }}</div>
    <div v-else-if="error" class="browser-pet-status browser-pet-status--error">{{ t('browserPet.unavailable', { model: modelLabel }) }}</div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
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

const mountEl = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref(false)
const ready = ref(false)
const modelType = ref<PetModelType>('live2d')
const modelLabel = ref('Live2D')
const browserInteractMode = ref(false)
const browserLocked = ref(false)
const zoomBounds = { min: 1.2, max: 3 }
const zoomScale = ref(typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches ? 1.48 : 1.7)
const emit = defineEmits<{ 'zoom-change': [scale: number] }>()
let renderer: PetRendererInstance | null = null
let resizeObserver: ResizeObserver | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null
let currentModelKey = ''
let ttsPlaybackToken = 0

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
  zoomScale.value = typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches ? 1.48 : 1.7
  emit('zoom-change', zoomScale.value)
}

const handleInputAction = (event: Event): void => {
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

const handleTtsPlayUrl = (event: Event): void => {
  // Electron already drives the dedicated pet window through petControl; the
  // embedded stage only needs local URL lip sync in browser mode.
  if (!renderer || window.petApi?.live2d) return
  const detail = (event as CustomEvent<{
    audio_url?: unknown
    petLinkEnabled?: unknown
  }>).detail
  if (detail?.petLinkEnabled === false) return
  const audioUrl = typeof detail?.audio_url === 'string' ? detail.audio_url.trim() : ''
  if (!audioUrl) return
  const token = ++ttsPlaybackToken
  void resolveBackendUrl(audioUrl)
    .then((resolvedUrl) => {
      if (!renderer || token !== ttsPlaybackToken) return
      return renderer.startLipSync(resolvedUrl)
    })
    .catch((error: unknown) => {
      console.debug('[BrowserPetStage] failed to start lip sync:', error)
    })
}

const handleTtsStop = (event: Event): void => {
  ttsPlaybackToken += 1
  const detail = (event as CustomEvent<{ interrupted?: unknown }>).detail
  renderer?.stopLipSync({ interrupted: detail?.interrupted === true })
}

const handleAudioEnded = (): void => {
  ttsPlaybackToken += 1
  renderer?.stopLipSync()
}

const handleLipSyncLevel = (event: Event): void => {
  if (!renderer || window.petApi?.live2d) return
  const detail = (event as CustomEvent<PetLipSyncLevelPayload>).detail
  if (!detail || typeof detail !== 'object') return
  renderer.setExternalLipSync(detail)
}

const handleLipSyncViseme = (event: Event): void => {
  if (!renderer || window.petApi?.live2d) return
  const detail = (event as CustomEvent<PetLipSyncVisemePayload>).detail
  if (!detail || typeof detail !== 'object') return
  renderer.setExternalViseme(detail)
}

defineExpose({ adjustZoom, resetZoom, zoomScale, zoomBounds })

onMounted(async () => {
  if (!mountEl.value) return
  window.addEventListener('yuizaki:input-action', handleInputAction)
  window.addEventListener('pet:llm-control', handleLlmControl)
  window.addEventListener('pet:tts-play-url', handleTtsPlayUrl)
  window.addEventListener('pet:tts-stop', handleTtsStop)
  window.addEventListener('pet:audio-ended', handleAudioEnded)
  window.addEventListener('pet:lipsync-level', handleLipSyncLevel)
  window.addEventListener('pet:lipsync-viseme', handleLipSyncViseme)
  emit('zoom-change', zoomScale.value)
  const mountId = `browser-pet-stage-${Math.random().toString(36).slice(2)}`
  mountEl.value.id = mountId
  try {
    let model: PetModelDefinition | undefined
    try {
      const [state, catalog] = await Promise.all([petControl.getState(), petControl.getCatalog()])
      const modelId = state.modelId || catalog.activeModelId
      model = catalog.models.find((item) => item.id === modelId) || catalog.models[0]
    } catch (cause) {
      console.warn('[BrowserPetStage] model catalog unavailable, using bundled Live2D', cause)
    }

    if (model) {
      modelType.value = model.type
      modelLabel.value = model.type === 'vrm' ? 'VRM' : 'Live2D'
    }
    const selectedType = model?.type || 'live2d'
    const selectedPath = modelAssetUrl(model)

    const { ensureCubismCore } = await import('@/pet-renderer-core')
    await ensureCubismCore()
    const { PetRenderer } = await import('@/pet-renderer')
    renderer = new PetRenderer(mountId)
    await renderer.init()
    const resizeRenderer = (): void => {
      const rect = mountEl.value?.getBoundingClientRect()
      if (rect && rect.width > 0 && rect.height > 0) {
        renderer?.resizeTo(rect.width, rect.height)
      }
    }
    resizeObserver = new ResizeObserver(resizeRenderer)
    resizeObserver.observe(mountEl.value)
    resizeRenderer()
    await renderer.applyBrowserConfig({
      modelType: selectedType,
      modelId: model?.id || 'yumi',
      modelPath: selectedPath,
      scale: selectedType === 'vrm' ? 0.96 : 0.9,
      clickThrough: false,
      locked: browserLocked.value,
      interactMode: browserInteractMode.value,
      opacity: 1,
      placement: 'center',
    })
    currentModelKey = `${selectedType}:${model?.id || 'yumi'}:${selectedPath}`
    ready.value = true
    refreshTimer = setInterval(async () => {
      if (!renderer) return
      try {
        const [state, catalog] = await Promise.all([petControl.getState(), petControl.getCatalog()])
        const nextModel = catalog.models.find((item) => item.id === (state.modelId || catalog.activeModelId)) || catalog.models[0]
        const nextType = nextModel?.type || 'live2d'
        const nextPath = modelAssetUrl(nextModel)
        const nextKey = `${nextType}:${nextModel?.id || 'yumi'}:${nextPath}`
        if (nextKey === currentModelKey) return
        currentModelKey = nextKey
        modelType.value = nextType
        modelLabel.value = nextType === 'vrm' ? 'VRM' : 'Live2D'
        ready.value = false
        await renderer.applyBrowserConfig({ modelType: nextType, modelId: nextModel?.id || 'yumi', modelPath: nextPath, scale: nextType === 'vrm' ? 0.96 : 0.9, clickThrough: false, locked: false, opacity: 1, placement: 'center' })
        ready.value = true
      } catch (cause) {
        console.warn('[BrowserPetStage] model refresh failed', cause)
      }
    }, 2500)
  } catch (cause) {
    console.warn('[BrowserPetStage] Live2D unavailable', cause)
    error.value = true
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('yuizaki:input-action', handleInputAction)
  window.removeEventListener('pet:llm-control', handleLlmControl)
  window.removeEventListener('pet:tts-play-url', handleTtsPlayUrl)
  window.removeEventListener('pet:tts-stop', handleTtsStop)
  window.removeEventListener('pet:audio-ended', handleAudioEnded)
  window.removeEventListener('pet:lipsync-level', handleLipSyncLevel)
  window.removeEventListener('pet:lipsync-viseme', handleLipSyncViseme)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = null
  renderer?.destroy()
  renderer = null
})
</script>

<style scoped>
.browser-pet-stage {
  position: relative;
  width: min(100%, 840px);
  height: min(82vh, 840px);
  min-height: 480px;
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
  transform: translateY(18%) scale(var(--browser-model-scale, 1.7));
  transform-origin: center center;
}

.browser-pet-fallback {
  object-fit: contain;
  object-position: center bottom;
  transform: translateY(12%) scale(1.42);
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

@media (max-width: 760px) {
  .browser-pet-stage {
    width: 100%;
    height: min(66vh, 580px);
    min-height: 300px;
  }

  .browser-pet-canvas.is-ready :deep(canvas) {
    transform: translateY(14%) scale(var(--browser-model-scale, 1.48));
  }

  .browser-pet-fallback {
    transform: translateY(8%) scale(1.22);
  }

}
</style>

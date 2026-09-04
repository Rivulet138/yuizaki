<template>
  <div class="browser-pet-stage" :data-model-type="modelType" :aria-label="`${modelLabel} 对话模型`">
    <img v-if="!ready && modelType === 'live2d'" class="browser-pet-fallback" src="/live2d/llm-live2d/yumi/yumi-stage.png" alt="" />
    <div
      ref="mountEl"
      class="browser-pet-canvas"
      :class="{ 'is-ready': ready }"
      :style="{ '--browser-model-scale': zoomScale }"
      aria-hidden="true"
    ></div>
    <div v-if="loading" class="browser-pet-status">{{ modelLabel }} 加载中</div>
    <div v-else-if="error" class="browser-pet-status browser-pet-status--error">{{ modelLabel }} 暂不可用</div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { PetRenderer as PetRendererInstance } from '@/pet-renderer'
import { petControl } from '@/utils/petControl'
import type { PetModelDefinition, PetModelType } from '@/../shared/pet-control'

const mountEl = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref(false)
const ready = ref(false)
const modelType = ref<PetModelType>('live2d')
const modelLabel = ref('Live2D')
const zoomBounds = { min: 1.2, max: 3 }
const zoomScale = ref(typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches ? 1.48 : 1.7)
const emit = defineEmits<{ 'zoom-change': [scale: number] }>()
let renderer: PetRendererInstance | null = null
let resizeObserver: ResizeObserver | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null
let currentModelKey = ''

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

defineExpose({ adjustZoom, resetZoom, zoomScale, zoomBounds })

onMounted(async () => {
  if (!mountEl.value) return
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
      locked: false,
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

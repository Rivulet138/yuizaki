<template>
  <div class="browser-pet-stage" :data-model-type="modelType" :aria-label="`${modelLabel} 对话模型`">
    <img v-if="!ready && modelType === 'live2d'" class="browser-pet-fallback" src="/live2d/llm-live2d/yumi/yumi-stage.png" alt="" />
    <div ref="mountEl" class="browser-pet-canvas" aria-hidden="true"></div>
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
let renderer: PetRendererInstance | null = null
let resizeObserver: ResizeObserver | null = null
let restoreDesktopPet = false
let stageActive = true

const isBrowserOnlyLaunch = (): boolean => {
  try {
    return new URL(window.location.href).searchParams.get('browser_only') === '1'
  } catch {
    return false
  }
}

onMounted(async () => {
  if (!mountEl.value) return
  const mountId = `browser-pet-stage-${Math.random().toString(36).slice(2)}`
  mountEl.value.id = mountId
  try {
    let model: PetModelDefinition | undefined
    try {
      const [state, catalog] = await Promise.all([petControl.getState(), petControl.getCatalog()])
      if (!window.petApi?.window && state.visible) {
        await petControl.setVisible(false)
        if (stageActive && !isBrowserOnlyLaunch()) {
          restoreDesktopPet = true
        }
      }
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
    const selectedPath = model?.assetPath
      ? model.assetPath.startsWith('/')
        ? model.assetPath
        : `./${selectedType === 'vrm' ? 'vrm' : 'live2d'}/${model.assetPath}`
      : './live2d/llm-live2d/yumi/yumi.model3.json'

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
      scale: selectedType === 'vrm' ? 0.8 : 0.74,
      clickThrough: false,
      locked: false,
      opacity: 1,
      placement: 'center',
    })
    ready.value = true
  } catch (cause) {
    console.warn('[BrowserPetStage] Live2D unavailable', cause)
    error.value = true
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  stageActive = false
  resizeObserver?.disconnect()
  resizeObserver = null
  renderer?.destroy()
  renderer = null
  if (restoreDesktopPet) {
    void petControl.setVisible(true).catch((cause) => {
      console.warn('[BrowserPetStage] failed to restore desktop pet visibility', cause)
    })
    restoreDesktopPet = false
  }
})
</script>

<style scoped>
.browser-pet-stage {
  position: relative;
  width: min(100%, 720px);
  height: min(78vh, 760px);
  min-height: 420px;
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

.browser-pet-fallback {
  object-fit: contain;
  object-position: center bottom;
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
    height: min(62vh, 520px);
    min-height: 300px;
  }
}
</style>

<template>
  <div class="browser-pet-stage" aria-label="Live2D 展示台">
    <img v-if="!ready" class="browser-pet-fallback" src="/live2d/llm-live2d/yumi/yumi-stage.png" alt="" />
    <div ref="mountEl" class="browser-pet-canvas" aria-hidden="true"></div>
    <div v-if="loading" class="browser-pet-status">Live2D 加载中</div>
    <div v-else-if="error" class="browser-pet-status browser-pet-status--error">展示台预览</div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { PetRenderer as PetRendererInstance } from '@/pet-renderer'

const mountEl = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref(false)
const ready = ref(false)
let renderer: PetRendererInstance | null = null

onMounted(async () => {
  if (!mountEl.value) return
  const mountId = `browser-pet-stage-${Math.random().toString(36).slice(2)}`
  mountEl.value.id = mountId
  try {
    const { PetRenderer } = await import('@/pet-renderer')
    renderer = new PetRenderer(mountId)
    await renderer.init()
    await renderer.applyBrowserConfig({
      modelType: 'live2d',
      modelId: 'yumi',
      modelPath: '/live2d/llm-live2d/yumi/yumi.model3.json',
      scale: 0.58,
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
  renderer?.destroy()
  renderer = null
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

<template>
  <el-button
    :disabled="disabled || !screenCaptureAvailable"
    :loading="previewLoading"
    @click="openSelector"
  >
    <el-icon><Crop /></el-icon>
    {{ buttonLabel || '选择区域' }}
  </el-button>

  <el-dialog
    v-model="dialogVisible"
    :title="dialogTitle || '选择观察区域'"
    width="min(920px, calc(100vw - 32px))"
    destroy-on-close
    append-to-body
  >
    <div v-loading="previewLoading" class="vision-region-selector">
      <div
        v-if="previewImage"
        class="vision-region-stage"
        @pointerdown="handlePointerDown"
        @pointermove="handlePointerMove"
        @pointerup="finishPointerDrag"
        @pointercancel="finishPointerDrag"
      >
        <img :src="previewImage" alt="当前显示器预览" draggable="false" />
        <div
          v-for="(style, index) in contextRegionStyles"
          :key="index"
          class="vision-region-context"
          :style="style"
        />
        <div class="vision-region-selection" :class="`is-${tone || 'capture'}`" :style="selectionStyle" />
      </div>
      <div v-else class="vision-region-empty">无法读取屏幕预览</div>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button :loading="previewLoading" @click="loadPreview">
        <el-icon><RefreshRight /></el-icon>
        刷新
      </el-button>
      <el-button type="primary" :disabled="!previewImage" @click="applySelection">
        {{ applyLabel || '应用区域' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Crop, RefreshRight } from '@element-plus/icons-vue'
import type { WorkspaceVisionSettings } from '@/../shared/workspace'
import {
  normalizedRegionFromPointerDrag,
  normalizedRegionFromWorkspace,
  workspaceRegionFromNormalized,
  type NormalizedVisionRegion,
} from '@/vision/region-selection'

const props = defineProps<{
  disabled?: boolean
  displayIndex: number
  displayWidth: number
  displayHeight: number
  region: WorkspaceVisionSettings['region']
  contextRegions?: WorkspaceVisionSettings['privacyMasks']
  buttonLabel?: string
  dialogTitle?: string
  applyLabel?: string
  tone?: 'capture' | 'privacy'
}>()

const emit = defineEmits<{
  apply: [region: WorkspaceVisionSettings['region']]
}>()

const dialogVisible = ref(false)
const previewLoading = ref(false)
const previewImage = ref('')
const selection = ref<NormalizedVisionRegion>({ x: 0.1, y: 0.1, width: 0.8, height: 0.8 })
const dragStart = ref<{ pointerId: number; x: number; y: number } | null>(null)

const screenCaptureAvailable = computed(() => Boolean(window.petApi?.screen?.capture))
const displaySize = computed(() => ({
  width: Math.max(1, props.displayWidth),
  height: Math.max(1, props.displayHeight),
}))
const selectionStyle = computed(() => ({
  left: `${selection.value.x * 100}%`,
  top: `${selection.value.y * 100}%`,
  width: `${selection.value.width * 100}%`,
  height: `${selection.value.height * 100}%`,
}))
const contextRegionStyles = computed(() => (props.contextRegions ?? []).map((region) => {
  const normalized = normalizedRegionFromWorkspace(region, displaySize.value)
  return {
    left: `${normalized.x * 100}%`,
    top: `${normalized.y * 100}%`,
    width: `${normalized.width * 100}%`,
    height: `${normalized.height * 100}%`,
  }
}))

const loadPreview = async () => {
  const capture = window.petApi?.screen?.capture
  if (!capture) return
  previewLoading.value = true
  try {
    const image = await capture(props.displayIndex, {
      format: 'jpeg',
      maxWidth: 1280,
      maxHeight: 720,
      quality: 68,
    })
    previewImage.value = typeof image === 'string' && image.startsWith('data:image/') ? image : ''
    if (!previewImage.value) ElMessage.error('屏幕预览不可用')
  } catch (error) {
    previewImage.value = ''
    ElMessage.error(error instanceof Error ? error.message : '屏幕预览不可用')
  } finally {
    previewLoading.value = false
  }
}

const openSelector = async () => {
  if (!screenCaptureAvailable.value) {
    ElMessage.warning('当前环境不支持屏幕预览')
    return
  }
  selection.value = normalizedRegionFromWorkspace(props.region, displaySize.value)
  dialogVisible.value = true
  await loadPreview()
}

const handlePointerDown = (event: PointerEvent) => {
  if (event.button !== 0) return
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  dragStart.value = { pointerId: event.pointerId, x: event.clientX, y: event.clientY }
  selection.value = normalizedRegionFromPointerDrag(
    dragStart.value,
    { x: event.clientX, y: event.clientY },
    target.getBoundingClientRect(),
  )
}

const handlePointerMove = (event: PointerEvent) => {
  const start = dragStart.value
  if (!start || start.pointerId !== event.pointerId) return
  selection.value = normalizedRegionFromPointerDrag(
    start,
    { x: event.clientX, y: event.clientY },
    (event.currentTarget as HTMLElement).getBoundingClientRect(),
  )
}

const finishPointerDrag = (event: PointerEvent) => {
  if (dragStart.value?.pointerId !== event.pointerId) return
  handlePointerMove(event)
  dragStart.value = null
}

const applySelection = () => {
  emit('apply', workspaceRegionFromNormalized(selection.value, displaySize.value))
  dialogVisible.value = false
}
</script>

<style scoped>
.vision-region-selector {
  display: flex;
  min-height: 240px;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid var(--yui-border);
  border-radius: 6px;
  background: #111827;
}

.vision-region-stage {
  position: relative;
  width: fit-content;
  max-width: 100%;
  cursor: crosshair;
  touch-action: none;
  user-select: none;
}

.vision-region-stage img {
  display: block;
  width: auto;
  max-width: 100%;
  max-height: 58vh;
  object-fit: contain;
  pointer-events: none;
}

.vision-region-selection {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid #22d3ee;
  background: rgb(34 211 238 / 16%);
  box-shadow: 0 0 0 9999px rgb(3 7 18 / 52%);
  pointer-events: none;
}

.vision-region-selection.is-privacy {
  border-color: #ef4444;
  background: rgb(239 68 68 / 22%);
}

.vision-region-context {
  position: absolute;
  box-sizing: border-box;
  border: 1px solid #f87171;
  background: rgb(127 29 29 / 52%);
  pointer-events: none;
}

.vision-region-empty {
  color: #cbd5e1;
  font-size: 13px;
}
</style>

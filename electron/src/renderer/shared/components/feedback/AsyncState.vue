<template>
  <div
    v-if="loading"
    class="async-state async-state--loading"
    role="status"
    aria-live="polite"
    :data-reduced-motion="reducedMotion.reduced.value ? 'true' : 'false'"
  >
    <div class="async-state__header">
      <span class="async-state__pulse"></span>
      <span>{{ loadingText || '正在加载数据…' }}</span>
    </div>
    <div class="skeleton-list">
      <div v-for="n in 3" :key="n" class="skeleton-row">
        <div class="skeleton-line w-3/4"></div>
        <div class="skeleton-line w-1/2"></div>
      </div>
    </div>
  </div>
  <div v-else-if="error" class="async-error" role="alert">
    <div class="async-error__icon">!</div>
    <div>
      <strong>{{ errorTitle || '加载失败' }}</strong>
      <p>{{ error }}</p>
      <button class="retry-btn" @click="$emit('retry')">{{ retryText || '重试' }}</button>
    </div>
  </div>
  <div v-else-if="empty" class="async-state async-state--empty">
    <el-empty :description="emptyText || '暂无数据'" :image-size="64">
      <template v-if="$slots.empty" #default>
        <slot name="empty" />
      </template>
    </el-empty>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { createReducedMotionObserver } from '@/app/runtime/reducedMotion'

defineProps<{
  loading?: boolean
  error?: string
  empty?: boolean
  emptyText?: string
  loadingText?: string
  errorTitle?: string
  retryText?: string
}>()

defineEmits<{ (e: 'retry'): void }>()

const reducedMotion = createReducedMotionObserver()
onMounted(reducedMotion.start)
onUnmounted(reducedMotion.stop)
</script>

<style scoped>
.async-state { padding: 12px 0; }
.async-state--loading,
.async-state--empty {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 120px;
}
.async-state__header {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}
.async-state__pulse {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #60a5fa;
  box-shadow: 0 0 0 0 rgba(96, 165, 250, 0.5);
  animation: pulse-ring 1.45s infinite;
}
.skeleton-list { display: flex; flex-direction: column; gap: 12px; }
.skeleton-row { display: flex; flex-direction: column; gap: 6px; padding: 10px 14px; }
.skeleton-line {
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
.w-3\/4 { width: 75%; }
.w-1\/2 { width: 50%; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@keyframes pulse-ring { 70% { box-shadow: 0 0 0 8px rgba(96, 165, 250, 0); } 100% { box-shadow: 0 0 0 0 rgba(96, 165, 250, 0); } }
.async-error {
  display: flex;
  gap: 12px;
  padding: 18px;
  color: #991b1b;
  border: 1px solid rgba(252, 165, 165, 0.7);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.96), rgba(255, 247, 237, 0.82));
}
.async-error__icon {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
  font-weight: 900;
  background: #ef4444;
}
.async-error p {
  margin: 4px 0 0;
  color: #b91c1c;
  font-size: 13px;
  line-height: 1.5;
}
.retry-btn {
  margin-top: 10px;
  border: 1px solid #fca5a5;
  border-radius: 8px;
  padding: 6px 16px;
  background: #fef2f2;
  color: #dc2626;
  cursor: pointer;
  font-size: 13px;
}

@media (prefers-reduced-motion: reduce) {
  .async-state__pulse,
  .skeleton-line {
    animation: none;
  }
}
</style>

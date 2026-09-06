import { onMounted, onUnmounted, watch } from 'vue'
import { getSocketClient } from '@/net/socketClient'

type RendererStage =
  | 'renderer_dom_content_loaded'
  | 'renderer_first_contentful_paint'
  | 'renderer_lcp'
  | 'socket_connected'

const finitePositive = (value: number): number | null => (
  Number.isFinite(value) && value >= 0 ? Math.round(value * 10) / 10 : null
)

/** Report content-free renderer milestones to the existing local metrics path. */
export function useClientPerformanceMetrics(): void {
  const socket = getSocketClient()
  const observers: PerformanceObserver[] = []
  let stopConnectionWatch: (() => void) | undefined
  let reportedLcp = false

  const report = (stage: RendererStage, elapsedMs: number): void => {
    const elapsed = finitePositive(elapsedMs)
    if (elapsed === null) return
    socket.sendClientTiming(stage, { elapsedMs: elapsed })
  }

  const observe = (type: 'paint' | 'largest-contentful-paint'): void => {
    if (typeof PerformanceObserver === 'undefined' || !PerformanceObserver.supportedEntryTypes?.includes(type)) return
    const observer = new PerformanceObserver((list) => {
      const entry = list.getEntries().at(-1)
      if (!entry) return
      if (type === 'paint' && entry.name === 'first-contentful-paint') {
        report('renderer_first_contentful_paint', entry.startTime)
      }
      if (type === 'largest-contentful-paint' && !reportedLcp) {
        reportedLcp = true
        report('renderer_lcp', entry.startTime)
        observer.disconnect()
      }
    })
    observer.observe({ type, buffered: true })
    observers.push(observer)
  }

  onMounted(() => {
    const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    if (navigation) {
      report('renderer_dom_content_loaded', navigation.domContentLoadedEventEnd - navigation.startTime)
    }
    observe('paint')
    observe('largest-contentful-paint')
    stopConnectionWatch = watch(socket.connected, (connected) => {
      if (!connected || !navigation) return
      report('socket_connected', performance.now() - navigation.startTime)
      stopConnectionWatch?.()
      stopConnectionWatch = undefined
    }, { immediate: true })
  })

  onUnmounted(() => {
    observers.forEach((observer) => observer.disconnect())
    stopConnectionWatch?.()
  })
}

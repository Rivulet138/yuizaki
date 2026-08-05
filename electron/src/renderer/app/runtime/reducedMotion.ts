import { ref, type Ref } from 'vue'

export interface ReducedMotionObserver {
  reduced: Ref<boolean>
  start: () => void
  stop: () => void
}

export const createReducedMotionObserver = (
  resolveMediaQuery: () => MediaQueryList | null = () => window.matchMedia?.('(prefers-reduced-motion: reduce)') ?? null,
): ReducedMotionObserver => {
  const reduced = ref(false)
  let mediaQuery: MediaQueryList | null = null
  let started = false

  const handleChange = (event: MediaQueryListEvent) => {
    reduced.value = event.matches
    document.documentElement.toggleAttribute('data-reduced-motion', event.matches)
  }

  const start = () => {
    if (started) return
    started = true
    mediaQuery = resolveMediaQuery()
    reduced.value = mediaQuery?.matches ?? false
    document.documentElement.toggleAttribute('data-reduced-motion', reduced.value)
    mediaQuery?.addEventListener('change', handleChange)
  }

  const stop = () => {
    if (!started) return
    started = false
    mediaQuery?.removeEventListener('change', handleChange)
    mediaQuery = null
  }

  return { reduced, start, stop }
}

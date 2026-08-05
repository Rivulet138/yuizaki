import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { createReducedMotionObserver } from '../app/runtime/reducedMotion'
import AsyncState from '../shared/components/feedback/AsyncState.vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('reduced motion observer', () => {
  it('tracks runtime preference changes and removes its listener', () => {
    let listener: ((event: MediaQueryListEvent) => void) | undefined
    const media = {
      matches: true,
      addEventListener: vi.fn((_name, callback) => { listener = callback }),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList
    const observer = createReducedMotionObserver(() => media)

    observer.start()
    expect(observer.reduced.value).toBe(true)
    listener?.({ matches: false } as MediaQueryListEvent)
    expect(observer.reduced.value).toBe(false)
    observer.stop()
    expect(media.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('defines global CSS suppression without hiding semantic state', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/renderer/assets/tailwind.css'), 'utf8')
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain('.status-dot.active')
    expect(css).toContain('.stream-caret')
    expect(css).toContain('.wave-bar')
    expect(css).toContain('.pending-dot')
    expect(css).toContain('.async-state__pulse')
    expect(css).toContain('.skeleton-line')
    expect(css).toContain('animation: none !important')
    expect(css).not.toContain('display: none')
  })

  it('updates a mounted async state when the motion preference changes', async () => {
    let listener: ((event: MediaQueryListEvent) => void) | undefined
    const media = {
      matches: false,
      addEventListener: vi.fn((_name, callback) => { listener = callback }),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList
    vi.stubGlobal('matchMedia', vi.fn(() => media))
    const wrapper = mount(AsyncState, { props: { loading: true } })
    expect(wrapper.get('[role="status"]').attributes('data-reduced-motion')).toBe('false')

    listener?.({ matches: true } as MediaQueryListEvent)
    await nextTick()
    expect(wrapper.get('[role="status"]').attributes('data-reduced-motion')).toBe('true')
    wrapper.unmount()
    expect(media.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    vi.unstubAllGlobals()
  })
})

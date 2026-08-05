import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'


const readRendererSource = (relativePath: string) =>
  readFileSync(`src/renderer/${relativePath}`, 'utf8')


describe('G004 companion Home contract', () => {
  it('composes the first viewport from focused avatar, status, and command components', () => {
    const source = readRendererSource('domains/companion/views/CompanionPanel.vue')
    const hero = readRendererSource('domains/companion/components/CompanionHero.vue')

    expect(source).toContain('<CompanionHero')
    expect(source).toContain('<CompanionQuickActions')
    expect(source).toContain('<CompanionActivitySummary')
    expect(source).toContain(':presentation-state="presentationState"')
    expect(source).toContain('runtimeState.availability')
    expect(source).toContain('runtimeState.permission')
    expect(hero).toContain('role="status"')
    expect(hero).toContain('aria-live="polite"')
  })

  it('wires daily commands to existing chat and pet controls', () => {
    const source = readRendererSource('domains/companion/views/CompanionPanel.vue')
    const quickActions = readRendererSource('domains/companion/components/CompanionQuickActions.vue')

    expect(source).toContain("modulePath('chat')")
    expect(source).toContain('chatStore.interrupt()')
    expect(source).toContain('chatStore.setTtsEnabled')
    expect(source).toContain('petControlClient.setDoNotDisturb')
    expect(quickActions).toContain('data-testid="companion-proactivity-preset"')
    expect(source).toContain("modulePath('agent-trace')")
    expect(source).toContain("modulePath('agent-governance')")
  })

  it('keeps maintenance editors off Home and routes to canonical advanced surfaces', () => {
    const source = readRendererSource('domains/companion/views/CompanionPanel.vue')

    expect(source).not.toContain('VisionRegionSelector')
    expect(source).not.toContain('saveCompanion')
    expect(source).not.toContain('handleDelete')
    expect(source).not.toContain('heartbeatLatestBehavior')
    expect(source).toContain("modulePath('pet')")
    expect(source).toContain("modulePath('settings')")
    expect(source).toContain("modulePath('prompt')")
    expect(source).toContain("modulePath('persona-memory')")
    expect(source).toContain("modulePath('memory')")
    expect(source).not.toContain('setInterval')
  })

  it('restores the validated proactivity preset in the global runtime bridge', () => {
    const source = readRendererSource('app/composables/useCompanionRuntimeBridge.ts')
    const panel = readRendererSource('domains/companion/views/CompanionPanel.vue')

    expect(source).toContain('readStoredProactivityPreset()')
    expect(source).toContain("value === 'standard' ? 'standard' : 'conservative'")
    expect(source).toContain('window.localStorage.setItem(PROACTIVITY_STORAGE_KEY, preset)')
    expect(source).toContain('controller.configure(PROACTIVITY_PRESETS[previous])')
    expect(panel).not.toContain('localStorage')
  })

  it('provides responsive and keyboard-visible command styling', () => {
    const quickActions = readRendererSource('domains/companion/components/CompanionQuickActions.vue')
    const hero = readRendererSource('domains/companion/components/CompanionHero.vue')

    expect(quickActions).toContain(':focus-visible')
    expect(quickActions).toContain('@media (max-width: 760px)')
    expect(quickActions).toContain('grid-template-columns: repeat(2, minmax(0, 1fr))')
    expect(hero).toContain('overflow-wrap: anywhere')
    expect(hero).toContain('@media (max-width: 760px)')
  })
})

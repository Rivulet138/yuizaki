import { describe, expect, it } from 'vitest'
import { staticNavigationModuleRecords } from '../../shared/navigation'
import { buildSidebarNavigation, buildSidebarRoute } from './sidebarNavigation'

describe('navigation contract', () => {
  it('keeps every enabled destination unique', () => {
    const enabledIds = staticNavigationModuleRecords
      .filter((module) => module.enabled !== false)
      .map((module) => module.id)

    expect(new Set(enabledIds).size).toBe(enabledIds.length)
  })

  it('keeps sidebar titles concise and functional', () => {
    for (const module of staticNavigationModuleRecords) {
      expect(module.title).toMatch(/^[\u3400-\u9fff]{4,5}$/)
    }
  })

  it('keeps chat, memory, and system settings as the primary destinations', () => {
    const primaryIds = staticNavigationModuleRecords
      .filter((module) => module.primary === true)
      .map((module) => module.id)

    expect(primaryIds).toEqual(['chat', 'memory', 'settings'])
  })

  it('keeps every non-primary destination reachable from advanced navigation', () => {
    const enabledMenus = staticNavigationModuleRecords.filter((module) => module.enabled !== false)
    const navigation = buildSidebarNavigation(enabledMenus)
    const primaryIds = navigation.primary.map((module) => module.id)
    const advancedIds = navigation.advanced.flatMap((group) => group.items.map((module) => module.id))

    expect(primaryIds).toEqual(['chat', 'memory', 'settings'])
    expect(navigation.advanced.map((group) => ({
      id: group.id,
      items: group.items.map((module) => module.id),
    }))).toEqual([
      { id: 'companion', items: ['prompt', 'pet', 'persona-memory'] },
      { id: 'system', items: ['infrastructure', 'deploy'] },
      { id: 'tools', items: ['tool', 'svc', 'plugins'] },
      { id: 'audit', items: ['agent-trace', 'agent-governance'] },
      { id: 'settings', items: ['i18n'] },
    ])
    expect(new Set([...primaryIds, ...advancedIds])).toEqual(new Set(enabledMenus.map((module) => module.id)))
  })

  it('encodes workspace and menu IDs used by sidebar links', () => {
    expect(buildSidebarRoute('场景 A/1', 'agent-trace')).toBe('/w/%E5%9C%BA%E6%99%AF%20A%2F1/agent-trace')
  })
})

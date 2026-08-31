import { describe, expect, it } from 'vitest'
import { staticNavigationModuleRecords } from '../../shared/navigation'
import { buildSidebarNavigation } from './sidebarNavigation'

describe('navigation contract', () => {
  it('keeps every enabled destination unique', () => {
    const enabledIds = staticNavigationModuleRecords
      .filter((module) => module.enabled !== false)
      .map((module) => module.id)

    expect(new Set(enabledIds).size).toBe(enabledIds.length)
  })

  it('keeps chat and memory as the only primary destinations', () => {
    const primaryIds = staticNavigationModuleRecords
      .filter((module) => module.primary === true)
      .map((module) => module.id)

    expect(primaryIds).toEqual(['chat', 'memory'])
  })

  it('keeps every non-primary destination reachable from advanced navigation', () => {
    const enabledMenus = staticNavigationModuleRecords
      .filter((module) => module.enabled !== false && module.id !== 'companion')
    const navigation = buildSidebarNavigation(enabledMenus)
    const primaryIds = navigation.primary.map((module) => module.id)
    const advancedIds = navigation.advanced.flatMap((group) => group.items.map((module) => module.id))

    expect(primaryIds).toEqual(['chat', 'memory'])
    expect(navigation.advanced.map((group) => ({
      id: group.id,
      items: group.items.map((module) => module.id),
    }))).toEqual([
      { id: 'companion', items: ['prompt', 'pet', 'persona-memory'] },
      { id: 'system', items: ['overview', 'infrastructure', 'deploy'] },
      { id: 'tools', items: ['tool', 'svc', 'plugins'] },
      { id: 'audit', items: ['agent-trace', 'agent-governance'] },
      { id: 'settings', items: ['settings', 'i18n'] },
    ])
    expect(new Set([...primaryIds, ...advancedIds])).toEqual(new Set(enabledMenus.map((module) => module.id)))
  })
})

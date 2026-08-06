import { describe, expect, it } from 'vitest'

import ToolPanel from '../domains/tools/views/ToolPanel.vue'
import AgentTracePanel from '../domains/system/views/AgentTracePanel.vue'
import InfrastructurePanel from '../domains/system/views/InfrastructurePanel.vue'
import PromptPanel from '../domains/prompt/views/PromptPanel.vue'
import { router } from '../router'
import { staticNavigationModuleRecords } from '../../shared/navigation'
import { enabledNavigationModules } from '../navigation/modules'

const loadRouteComponent = async (routeName: string) => {
  const route = router.getRoutes().find(record => record.name === routeName)
  expect(route).toBeTruthy()
  const component = route?.components?.default
  if (typeof component === 'function') {
    const loaded = await (component as () => Promise<{ default?: unknown }>)()
    return loaded.default
  }
  if (component && typeof component === 'object' && '__asyncLoader' in component) {
    const loader = (component as { __asyncLoader?: () => Promise<{ default?: unknown }> }).__asyncLoader
    expect(typeof loader).toBe('function')
    const loaded = await loader?.()
    return loaded?.default
  }
  return component
}

describe('platform smoke', () => {
  it('contains core desktop-pet modules', () => {
    const modules = enabledNavigationModules()
    const ids = modules.map((module) => module.id)
    expect(ids).toContain('companion')
    expect(ids).toContain('prompt')
    expect(ids).toContain('agent-trace')
    expect(ids).toContain('tool')
    expect(ids).toContain('plugins')
  })

  it('keeps renderer modules aligned with the trusted local navigation inventory', () => {
    const localIds = enabledNavigationModules().map((module) => module.id)
    const sharedIds = staticNavigationModuleRecords.map((module) => module.id)

    expect(localIds).toEqual(sharedIds)
    expect(localIds).toContain('i18n')
  })

  it('maps the task center route to the intended panel', async () => {
    expect(await loadRouteComponent('agent-trace')).toBe(AgentTracePanel)
  })

  it('maps capability center route to the intended panel', async () => {
    expect(await loadRouteComponent('tool')).toBe(ToolPanel)
  })

  it('maps prompt route to the dedicated prompt panel', async () => {
    expect(await loadRouteComponent('prompt')).toBe(PromptPanel)
  })

  it('navigates to the infrastructure panel route', async () => {
    expect(await loadRouteComponent('infrastructure')).toBe(InfrastructurePanel)
    await router.push('/w/default/infrastructure')
    expect(router.currentRoute.value.name).toBe('infrastructure')
  })
})

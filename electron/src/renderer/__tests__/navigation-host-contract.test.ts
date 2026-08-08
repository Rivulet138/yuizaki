import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { adminNavigationModules, enabledNavigationModules, primaryNavigationModules } from '../navigation/modules'
import { staticNavigationModuleRecords } from '../../shared/navigation'
import { router } from '../router'

const appShell = readFileSync(resolve(process.cwd(), 'src/renderer/app/AppShell.vue'), 'utf8')
const navigationModules = readFileSync(resolve(process.cwd(), 'src/renderer/navigation/modules.ts'), 'utf8')
const svcPanel = readFileSync(resolve(process.cwd(), 'src/renderer/domains/tools/views/SVCPanel.vue'), 'utf8')
const toolPanel = readFileSync(resolve(process.cwd(), 'src/renderer/domains/tools/views/ToolPanel.vue'), 'utf8')
const overviewPanel = readFileSync(resolve(process.cwd(), 'src/renderer/domains/system/views/OverviewPanel.vue'), 'utf8')

describe('navigation view host', () => {
  it('does not block async routes behind an out-in keep-alive transition', () => {
    expect(appShell).toContain('v-slot="{ Component, route }"')
    expect(appShell).toContain(':key="route.name"')
    expect(appShell).not.toContain('mode="out-in"')
  })

  it('uses the navigation i18n namespace instead of the retired workbench namespace', () => {
    expect(navigationModules).toContain('`navigation.${module.id}.title`')
    expect(navigationModules).toContain('`navigation.${module.id}.desc`')
    expect(navigationModules).not.toContain('`workbench.${module.id}')
    expect(svcPanel).toContain("t('navigation.svc.title')")
    expect(svcPanel).not.toContain("t('workbench.svc.title')")
  })

  it('keeps the desktop pet primary navigation focused on daily use', () => {
    expect(primaryNavigationModules().map((module) => module.id)).toEqual([
      'chat',
      'memory',
    ])
    expect(adminNavigationModules().map((module) => module.id)).toEqual(expect.arrayContaining([
      'tool',
      'prompt',
      'pet',
      'agent-trace',
      'settings',
    ]))
    expect(staticNavigationModuleRecords).toHaveLength(16)
    expect(enabledNavigationModules()).toHaveLength(16)
  })

  it('retires the standalone companion home while preserving its deep link', () => {
    const companionRoute = router.getRoutes().find((route) => route.name === 'companion')

    expect(companionRoute?.redirect).toBeTypeOf('function')
    expect(staticNavigationModuleRecords.find((module) => module.id === 'companion')?.primary).toBe(false)
  })

  it('preserves every advanced route as a deep link', () => {
    for (const module of staticNavigationModuleRecords) {
      const resolved = router.resolve(`/w/default/${module.id}`)
      expect(resolved.name).toBe(module.id)
    }
    expect(router.resolve('/w/default').redirectedFrom).toBeUndefined()
    expect(router.resolve('/w/default/tool').name).toBe('tool')
    expect(router.resolve('/w/default/settings').name).toBe('settings')
    expect(router.resolve('/w/default/agent-trace').name).toBe('agent-trace')
  })

  it('links canonical administration views to their specialist routes', () => {
    expect(toolPanel).toContain("canonicalPath('plugins')")
    expect(toolPanel).toContain("canonicalPath('agent-governance')")
    expect(overviewPanel).toContain("canonicalPath('infrastructure')")
    expect(overviewPanel).toContain("canonicalPath('deploy')")
  })
})

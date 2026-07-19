import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { adminNavigationModules, primaryNavigationModules } from '../navigation/modules'

const appShell = readFileSync(resolve(process.cwd(), 'src/renderer/app/AppShell.vue'), 'utf8')
const navigationModules = readFileSync(resolve(process.cwd(), 'src/renderer/navigation/modules.ts'), 'utf8')
const svcPanel = readFileSync(resolve(process.cwd(), 'src/renderer/domains/tools/views/SVCPanel.vue'), 'utf8')

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
      'companion',
      'chat',
      'memory',
      'tool',
    ])
    expect(adminNavigationModules().map((module) => module.id)).toEqual(expect.arrayContaining([
      'prompt',
      'pet',
      'agent-trace',
      'settings',
    ]))
  })
})

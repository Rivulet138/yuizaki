import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('recoverable onboarding startup contract', () => {
  it('creates the local control/UI surfaces before starting the recoverable backend operation', () => {
    const source = fs.readFileSync(path.resolve(__dirname, '../index.ts'), 'utf8')
    const controlStart = source.indexOf('await controlServer.start()')
    const panelCreate = source.indexOf('petWindow.create(buildPanelRuntimeOptions()')
    const backendStart = source.indexOf('onboardingCoordinator.startBackend()')

    expect(controlStart).toBeGreaterThan(0)
    expect(panelCreate).toBeGreaterThan(controlStart)
    expect(backendStart).toBeGreaterThan(panelCreate)
    expect(source.slice(panelCreate, backendStart)).not.toContain('app.quit()')
    expect(source.slice(backendStart, source.indexOf('if (e2eActivation.active', backendStart))).not.toContain('app.quit()')
  })

  it('wires MCP refresh to the fixed authenticated Python readiness action', () => {
    const source = fs.readFileSync(path.resolve(__dirname, '../index.ts'), 'utf8')
    expect(source).toContain('/api/system/onboarding/readiness/action')
    expect(source).toContain("'x-yuizaki-backend-token': controlServer.getControlToken()")
    expect(source).toContain("body: JSON.stringify({ actionId: 'mcp.refresh_existing' })")
    expect(source).not.toContain('/api/system/onboarding/action')
  })
})

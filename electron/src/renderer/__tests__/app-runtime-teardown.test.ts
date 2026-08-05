import { describe, expect, it, vi } from 'vitest'
import { createAppRuntimeTeardown } from '../app/runtime/appRuntimeTeardown'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('renderer runtime teardown', () => {
  it('shares one awaitable teardown and disconnects exactly once', async () => {
    const stop = vi.fn()
    const disconnect = vi.fn()
    const teardown = createAppRuntimeTeardown({ stop, disconnect })

    const first = teardown.run()
    const second = teardown.run()
    expect(second).toBe(first)
    await Promise.all([first, second, teardown.run()])
    expect(stop).toHaveBeenCalledTimes(1)
    expect(disconnect).toHaveBeenCalledTimes(1)
  })

  it('keeps AppShell as the renderer SocketClient teardown owner', () => {
    const shell = readFileSync(resolve(process.cwd(), 'src/renderer/app/AppShell.vue'), 'utf8')
    const orchestrator = readFileSync(resolve(process.cwd(), 'src/renderer/app/orchestrators/useAppOrchestrator.ts'), 'utf8')
    const bridge = readFileSync(resolve(process.cwd(), 'src/renderer/app/composables/useCompanionRuntimeBridge.ts'), 'utf8')
    expect(shell.match(/getSocketClient\(\)\.disconnect\(\)/g)).toHaveLength(1)
    expect(shell).toContain('void teardownAppRuntime()')
    expect(orchestrator).not.toContain('.disconnect()')
    expect(bridge).not.toContain('.disconnect()')
  })

  it('keeps visual capture bound to Agent turns instead of a background timer', () => {
    const shell = readFileSync(resolve(process.cwd(), 'src/renderer/app/AppShell.vue'), 'utf8')

    expect(shell).toContain('chatStore.setAgentTurnPreparation(prepareAgentVisualContext)')
    expect(shell).toContain("mode: 'vision'")
    expect(shell).toContain("captureReason: forceEnabled ? 'manual' : 'agent_turn'")
    expect(shell).not.toContain('visualFrameTimer')
    expect(shell).not.toContain('restartVisualFrameTimer')
    expect(shell).not.toContain('window.setInterval(() => {\n    void captureRealtimeVisualFrame')
  })
})

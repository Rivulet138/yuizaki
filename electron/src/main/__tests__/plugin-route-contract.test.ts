import { describe, expect, it } from 'vitest'
import { loadPluginsFromDisk } from '../plugin-loader'
import { PluginRegistry } from '../plugin-registry'

describe('plugin route contract', () => {
  it('loads example plugin route with executable handler path', () => {
    const registry = new PluginRegistry()
    const plugins = loadPluginsFromDisk(registry)
    const plugin = plugins.find((item) => item.id === 'example-manifest-plugin')

    expect(plugin).toBeTruthy()
    expect(plugin?.routes?.[0]?.id).toBe('plugin-list-route')
    expect(plugin?.routes?.[0]?.handler).toContain('plugin-list-route.mjs')
    expect(plugin?.permissions.agentBridge).toBe(true)
  })

  it('registers execution policy defaults', () => {
    const registry = new PluginRegistry()
    const plugins = loadPluginsFromDisk(registry)
    const plugin = plugins.find((item) => item.id === 'example-manifest-plugin')

    expect(plugin?.execution.maxExecutionTimeMs).toBeGreaterThan(0)
    expect(plugin?.execution.maxConcurrentExecutions).toBeGreaterThan(0)
    expect(typeof plugin?.execution.allowCancellation).toBe('boolean')
  })
})

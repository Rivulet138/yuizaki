import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { PluginRegistry } from '../plugin-registry'
import type { DesktopPetPlugin } from '../../shared/plugin'

const plugin: DesktopPetPlugin = {
  manifestVersion: 2,
  id: 'test-plugin',
  name: 'Test Plugin',
  permissions: {
    routes: ['run'],
    toolScopes: [],
    modelScopes: [],
  },
  execution: {
    maxExecutionTimeMs: 1000,
    maxConcurrentExecutions: 1,
    allowCancellation: true,
  },
  routes: [
    {
      id: 'run',
      namespace: 'plugin',
      handler: 'fake-handler',
    },
  ],
}

describe('PluginRegistry', () => {
  it('tracks execution lifecycle', () => {
    const registry = new PluginRegistry()
    registry.register(plugin)

    const execution = registry.startExecution(plugin.id, 'run', 1000)
    expect(registry.getActiveExecutionCount(plugin.id)).toBe(1)

    registry.finishExecution(plugin.id, execution.invocationId)
    expect(registry.getActiveExecutionCount(plugin.id)).toBe(0)
  })

  it('records audit entries', () => {
    const registry = new PluginRegistry()
    registry.register(plugin)

    registry.recordAudit({
      timestamp: new Date().toISOString(),
      pluginId: plugin.id,
      routeId: 'run',
      status: 'ok',
    })

    const snapshot = registry.snapshot()
    expect(snapshot.audit).toHaveLength(1)
    expect(snapshot.pluginStates[0]?.executionIsolation).toBe('node-permission-process')
    expect(snapshot.pluginStates[0]?.stats.okCount).toBe(1)
  })

  it('exposes desktop pet event contributions in the public snapshot and contribution summary', () => {
    const registry = new PluginRegistry()
    registry.register({
      ...plugin,
      petEvents: [
        {
          event: 'onPetClicked',
          routeId: 'run',
          description: 'React to desktop pet clicks',
        },
      ],
    })

    const snapshot = registry.snapshot()
    expect(snapshot.plugins[0]?.petEvents).toEqual([
      {
        event: 'onPetClicked',
        routeId: 'run',
        description: 'React to desktop pet clicks',
      },
    ])
    expect(snapshot.contributionSummary.find((item) => item.category === 'event')).toEqual(
      expect.objectContaining({
        count: 1,
        items: ['test-plugin:onPetClicked'],
      }),
    )
  })

  it('redacts private filesystem paths from public snapshots without changing executable plugin state', () => {
    const registry = new PluginRegistry()
    const handlerPath = path.resolve('plugins/private-plugin/handler.mjs')
    const manifestPath = path.resolve('plugins/private-plugin/plugin.json')
    const assetPath = path.resolve('plugins/private-plugin/model/model3.json')
    const pluginWithPrivatePaths: DesktopPetPlugin = {
      ...plugin,
      id: 'private-plugin',
      manifestPath,
      routes: [
        {
          id: 'run',
          namespace: 'plugin',
          handler: handlerPath,
        },
      ],
      modelProviders: [
        {
          id: 'private-model',
          modelType: 'live2d',
          name: 'Private Model',
          assetPath,
        },
      ],
    }
    registry.register(pluginWithPrivatePaths)
    registry.recordLoadFailure({
      manifestPath,
      pluginId: 'private-plugin',
      reason: 'validation_failed',
      validationIssues: [{ field: 'routes[0].handler', message: 'bad handler', severity: 'error' }],
      occurredAt: new Date().toISOString(),
    })

    const snapshot = registry.snapshot()
    const publicPlugin = snapshot.plugins.find((item) => item.id === 'private-plugin')

    expect(registry.getPluginById('private-plugin')?.routes?.[0]?.handler).toBe(handlerPath)
    expect(publicPlugin).not.toHaveProperty('manifestPath')
    expect(publicPlugin?.routes?.[0]).not.toHaveProperty('handler')
    expect(snapshot.routes.find((route) => route.id === 'run')).not.toHaveProperty('handler')
    expect(publicPlugin?.modelProviders?.[0]).not.toHaveProperty('assetPath')
    expect(snapshot.modelProviders.find((provider) => provider.id === 'private-model')).not.toHaveProperty('assetPath')
    expect(snapshot.loadFailures[0]?.manifestPath).toBe('plugin.json')
  })
})

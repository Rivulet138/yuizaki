import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { loadPluginsFromDisk, resolvePluginRootDir } from '../plugin-loader'
import { PluginRegistry } from '../plugin-registry'

describe('plugin-loader', () => {
  it('resolves plugin root directory when plugins folder exists', () => {
    const root = resolvePluginRootDir()
    expect(root).toBeTruthy()
  })

  it('loads example manifest plugin from disk', () => {
    const registry = new PluginRegistry()
    const loaded = loadPluginsFromDisk(registry)
    expect(loaded.some((plugin) => plugin.id === 'example-manifest-plugin')).toBe(true)
  })

  it('rejects unknown manifest fields instead of accepting compatibility input', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'legacy-ui-plugin')

    try {
      fs.mkdirSync(pluginDir, { recursive: true })
      fs.writeFileSync(
        path.join(pluginDir, 'plugin.json'),
        JSON.stringify({
          manifestVersion: 2,
          id: 'legacy-ui-plugin',
          name: 'Legacy UI Plugin',
          permissions: {
            routes: [],
            toolScopes: ['clock'],
            modelScopes: [],
          },
          obsoleteField: [{ id: 'legacy-panel' }],
          toolCapabilities: [
            {
              id: 'clock',
              name: 'Clock',
              desc: 'Reads the local clock',
            },
          ],
        }),
        'utf8',
      )

      const registry = new PluginRegistry()
      const loaded = loadPluginsFromDisk(registry, pluginRoot)
      const snapshot = registry.snapshot()

      expect(loaded).toHaveLength(0)
      expect(snapshot.plugins).toHaveLength(0)
      expect(snapshot.loadFailures[0]?.validationIssues).toContainEqual({
        field: 'obsoleteField',
        message: 'Unknown plugin manifest field: obsoleteField',
        severity: 'error',
      })
    } finally {
      fs.rmSync(pluginRoot, { recursive: true, force: true })
    }
  })

  it('rejects plugin route handlers outside the plugin directory', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'bad-plugin')
    fs.mkdirSync(pluginDir, { recursive: true })
    fs.writeFileSync(path.join(pluginRoot, 'outside.mjs'), 'export default () => ({ status: 200 })', 'utf8')
    fs.writeFileSync(
      path.join(pluginDir, 'plugin.json'),
      JSON.stringify({
        manifestVersion: 2,
        id: 'bad-plugin',
        name: 'Bad Plugin',
        permissions: {
          routes: ['escape'],
          toolScopes: [],
          modelScopes: [],
        },
        routes: [
          {
            id: 'escape',
            namespace: 'plugin',
            handler: '../outside.mjs',
          },
        ],
      }),
      'utf8',
    )

    const registry = new PluginRegistry()
    const loaded = loadPluginsFromDisk(registry, pluginRoot)
    const snapshot = registry.snapshot()

    expect(loaded).toHaveLength(0)
    expect(snapshot.loadFailures[0]?.pluginId).toBe('bad-plugin')
    expect(snapshot.loadFailures[0]?.validationIssues.some((issue) => issue.field === 'routes[0].handler')).toBe(true)
  })

  it('rejects route contributions that are not listed in route permissions', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'unpermitted-route-plugin')

    try {
      fs.mkdirSync(pluginDir, { recursive: true })
      fs.writeFileSync(path.join(pluginDir, 'handler.mjs'), 'export default () => ({ status: 200 })', 'utf8')
      fs.writeFileSync(
        path.join(pluginDir, 'plugin.json'),
        JSON.stringify({
          manifestVersion: 2,
          id: 'unpermitted-route-plugin',
          name: 'Unpermitted Route Plugin',
          permissions: {
            routes: [],
            toolScopes: [],
            modelScopes: [],
          },
          routes: [
            {
              id: 'run',
              namespace: 'plugin',
              handler: './handler.mjs',
            },
          ],
        }),
        'utf8',
      )

      const registry = new PluginRegistry()
      const loaded = loadPluginsFromDisk(registry, pluginRoot)
      const snapshot = registry.snapshot()

      expect(loaded).toHaveLength(0)
      expect(snapshot.loadFailures[0]?.pluginId).toBe('unpermitted-route-plugin')
      expect(snapshot.loadFailures[0]?.validationIssues).toContainEqual({
        field: 'permissions.routes',
        message: 'Route contribution is not permitted: run',
        severity: 'error',
      })
    } finally {
      fs.rmSync(pluginRoot, { recursive: true, force: true })
    }
  })

  it('loads desktop pet event subscriptions when the target route is permitted', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'pet-event-plugin')

    try {
      fs.mkdirSync(pluginDir, { recursive: true })
      fs.writeFileSync(path.join(pluginDir, 'handler.mjs'), 'export default () => ({ status: 200 })', 'utf8')
      fs.writeFileSync(
        path.join(pluginDir, 'plugin.json'),
        JSON.stringify({
          manifestVersion: 2,
          id: 'pet-event-plugin',
          name: 'Pet Event Plugin',
          permissions: {
            routes: ['react'],
            toolScopes: [],
            modelScopes: [],
          },
          routes: [
            {
              id: 'react',
              namespace: 'plugin',
              handler: './handler.mjs',
            },
          ],
          petEvents: [
            {
              event: 'onPetClicked',
              routeId: 'react',
              description: 'React when the desktop pet is clicked',
            },
          ],
        }),
        'utf8',
      )

      const registry = new PluginRegistry()
      const loaded = loadPluginsFromDisk(registry, pluginRoot)

      expect(loaded).toHaveLength(1)
      expect(loaded[0]?.petEvents).toEqual([
        {
          event: 'onPetClicked',
          routeId: 'react',
          description: 'React when the desktop pet is clicked',
        },
      ])
    } finally {
      fs.rmSync(pluginRoot, { recursive: true, force: true })
    }
  })

  it('rejects desktop pet event subscriptions that target unpermitted routes', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'bad-pet-event-plugin')

    try {
      fs.mkdirSync(pluginDir, { recursive: true })
      fs.writeFileSync(path.join(pluginDir, 'handler.mjs'), 'export default () => ({ status: 200 })', 'utf8')
      fs.writeFileSync(
        path.join(pluginDir, 'plugin.json'),
        JSON.stringify({
          manifestVersion: 2,
          id: 'bad-pet-event-plugin',
          name: 'Bad Pet Event Plugin',
          permissions: {
            routes: ['run'],
            toolScopes: [],
            modelScopes: [],
          },
          routes: [
            {
              id: 'run',
              namespace: 'plugin',
              handler: './handler.mjs',
            },
          ],
          petEvents: [
            {
              event: 'onPetClicked',
              routeId: 'missing',
            },
          ],
        }),
        'utf8',
      )

      const registry = new PluginRegistry()
      const loaded = loadPluginsFromDisk(registry, pluginRoot)
      const snapshot = registry.snapshot()

      expect(loaded).toHaveLength(0)
      expect(snapshot.loadFailures[0]?.pluginId).toBe('bad-pet-event-plugin')
      expect(snapshot.loadFailures[0]?.validationIssues).toContainEqual({
        field: 'petEvents.routeId',
        message: 'Unknown pet event route target: missing',
        severity: 'error',
      })
    } finally {
      fs.rmSync(pluginRoot, { recursive: true, force: true })
    }
  })

  it('rejects plugin route handlers that escape through a symlinked directory', () => {
    const pluginRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-root-'))
    const pluginDir = path.join(pluginRoot, 'linked-plugin')
    const outsideDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-plugin-outside-'))
    const linkDir = path.join(pluginDir, 'linked')

    try {
      fs.mkdirSync(pluginDir, { recursive: true })
      fs.writeFileSync(path.join(outsideDir, 'escape.mjs'), 'export default () => ({ status: 200 })', 'utf8')
      try {
        fs.symlinkSync(outsideDir, linkDir, process.platform === 'win32' ? 'junction' : 'dir')
      } catch {
        return
      }

      fs.writeFileSync(
        path.join(pluginDir, 'plugin.json'),
        JSON.stringify({
          manifestVersion: 2,
          id: 'linked-plugin',
          name: 'Linked Plugin',
          permissions: {
            routes: ['escape'],
            toolScopes: [],
            modelScopes: [],
          },
          routes: [
            {
              id: 'escape',
              namespace: 'plugin',
              handler: 'linked/escape.mjs',
            },
          ],
        }),
        'utf8',
      )

      const registry = new PluginRegistry()
      const loaded = loadPluginsFromDisk(registry, pluginRoot)
      const snapshot = registry.snapshot()

      expect(loaded).toHaveLength(0)
      expect(snapshot.loadFailures[0]?.pluginId).toBe('linked-plugin')
      expect(snapshot.loadFailures[0]?.validationIssues.some((issue) => issue.field === 'routes[0].handler')).toBe(true)
    } finally {
      fs.rmSync(pluginRoot, { recursive: true, force: true })
      fs.rmSync(outsideDir, { recursive: true, force: true })
    }
  })
})

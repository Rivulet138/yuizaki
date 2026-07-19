import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { isPluginCommandAllowed, isPluginHostAllowed, isPluginPathAllowed } from '../plugin-policy'

describe('plugin-policy', () => {
  it('denies host and path access when no allowlist is declared', () => {
    expect(isPluginHostAllowed(undefined, 'example.test')).toBe(false)
    expect(isPluginHostAllowed([], 'example.test')).toBe(false)
    expect(isPluginPathAllowed(undefined, path.join('C:', 'tmp', 'yuizaki-plugin'))).toBe(false)
    expect(isPluginPathAllowed([], path.join('C:', 'tmp', 'yuizaki-plugin'))).toBe(false)
  })

  it('does not treat sibling paths with matching prefixes as allowed', () => {
    const base = path.join('C:', 'tmp', 'yuizaki-plugin')
    const sibling = path.join('C:', 'tmp', 'yuizaki-plugin-evil', 'payload.js')

    expect(isPluginPathAllowed([base], sibling)).toBe(false)
  })

  it('allows the base path and descendants', () => {
    const base = path.join('C:', 'tmp', 'yuizaki-plugin')

    expect(isPluginPathAllowed([base], base)).toBe(true)
    expect(isPluginPathAllowed([base], path.join(base, 'routes', 'handler.js'))).toBe(true)
  })

  it('preserves Linux path case while treating Windows paths case-insensitively', () => {
    expect(isPluginPathAllowed(['/opt/Yuizaki/plugin'], '/opt/yuizaki/plugin/handler.js', 'linux')).toBe(false)
    expect(isPluginPathAllowed(['C:/Yuizaki/plugin'], 'c:/yuizaki/plugin/handler.js', 'win32')).toBe(true)
  })

  it('requires exact command allowlist matches', () => {
    expect(isPluginCommandAllowed(undefined, 'node')).toBe(false)
    expect(isPluginCommandAllowed(['node'], 'node')).toBe(true)
    expect(isPluginCommandAllowed(['node'], 'node.exe')).toBe(false)
  })
})

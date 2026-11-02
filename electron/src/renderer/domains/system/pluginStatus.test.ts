import { describe, expect, it } from 'vitest'
import { countEnabledPlugins } from './pluginStatus'

describe('enabled plugin count', () => {
  it('counts unique enabled plugins, including degraded and error states', () => {
    expect(countEnabledPlugins([
      { pluginId: 'one', status: 'loaded' },
      { pluginId: 'one', status: 'loaded' },
      { pluginId: 'two', status: 'degraded' },
      { pluginId: 'three', status: 'error' },
      { pluginId: 'four', status: 'blocked' },
    ])).toBe(3)
    expect(countEnabledPlugins([])).toBe(0)
  })
})

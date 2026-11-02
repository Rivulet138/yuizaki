import type { PluginRuntimeState } from '../../../shared/plugin'

export const countEnabledPlugins = (states: ReadonlyArray<Pick<PluginRuntimeState, 'pluginId' | 'status'>>): number =>
  new Set(states.filter((state) => state.status !== 'blocked').map((state) => state.pluginId)).size

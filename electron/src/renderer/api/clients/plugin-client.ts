import type { PluginRegistrySnapshot } from '../../../shared/plugin'
import { CONTROL_ORIGIN, requestJson } from './http-client'

export const pluginClient = {
  list: async (): Promise<PluginRegistrySnapshot> => requestJson(`${CONTROL_ORIGIN}/api/plugin/list`),
  cancelExecution: async (
    pluginId: string,
    routeId: string,
    runId: string,
  ): Promise<{ ok: boolean; invocationId: string; status: string }> =>
    requestJson(`${CONTROL_ORIGIN}/api/plugin/${encodeURIComponent(pluginId)}/${encodeURIComponent(routeId)}?runId=${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    }),
}

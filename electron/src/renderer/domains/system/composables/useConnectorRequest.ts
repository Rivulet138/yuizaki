import { useDomainRequest } from '@/shared/composables/useDomainRequest'

// Each connector has its own latest response; refreshing WeChat must not discard QQ.
export function useConnectorRequest<T>(connectorIds: readonly string[]) {
  const requests = Object.fromEntries(connectorIds.map((id) => [id, useDomainRequest<T>()]))
  return {
    get loading() {
      return Object.values(requests).some((request) => request.loading)
    },
    get error() {
      return Object.values(requests).map((request) => request.error).filter(Boolean).join(' · ') || null
    },
    execute: (connectorId: string, task: () => Promise<T>) => requests[connectorId].execute(task),
    isCurrent: (result: T | null) => Object.values(requests).some((request) => request.isCurrent(result)),
  }
}

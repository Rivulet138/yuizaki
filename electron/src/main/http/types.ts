import type { IncomingMessage, ServerResponse } from 'http'
import type { Live2DWindow } from '../live2d-window'
import type { PetWindow } from '../window'
import type { PetStateStore } from '../pet-state-store'
import type { PetModelCatalog } from '../pet-model-catalog'
import type { PetControlState } from '../../shared/pet-control'
import type { PluginRegistry } from '../plugin-registry'
import type { BackendApiTokenStoreLike } from '../backend-api-token-store'
import type { ProviderCredentialStore } from '../provider-credential-store'

export interface HttpRouteContext {
  live2dWindow: Live2DWindow
  petWindow: PetWindow
  petStateStore: PetStateStore
  petModelCatalog: PetModelCatalog
  pluginRegistry: PluginRegistry
  backendApiToken: string
  backendApiTokenStore: BackendApiTokenStoreLike
  providerCredentialStore: ProviderCredentialStore
  adminTokenStore: {
    getSummaryAdminToken: () => string
    setSummaryAdminToken: (token: string) => { ok: boolean; hasToken: boolean }
    clearSummaryAdminToken: () => { ok: boolean }
  }
  applyPetStateToRenderer: ((state: PetControlState) => void) | undefined
  applyStateToLive2D: (state: PetControlState) => PetControlState
}

export type HttpRouteHandler = (
  req: IncomingMessage,
  res: ServerResponse,
  method: string,
  url: URL,
  ctx: HttpRouteContext,
) => Promise<boolean>

import { CONTROL_ORIGIN, requestJson } from './http-client'
import type {
  LocalModelImportResponse,
  LocalModelPickerResponse,
  ModelResourceStatusPayload,
  ManagedModelResourceId,
  PetImportableModelType,
  ResourceCancelResult,
  ResourceCommandResult,
  ResourceRemovalResult,
  StorageCategoryId,
  StorageCleanupResult,
  StorageStatusPayload,
} from '@/../shared/resource-manager'

const RESOURCE_OPERATION_TIMEOUT_MS = 30 * 60 * 1000

export const resourceClient = {
  status: async () => requestJson<ModelResourceStatusPayload>(`${CONTROL_ORIGIN}/api/system/resources`),
  prepare: async (resources: ManagedModelResourceId[]) => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/prepare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resources }),
    timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS,
  }),
  cancel: async (resources: ManagedModelResourceId[]) => requestJson<ResourceCancelResult>(`${CONTROL_ORIGIN}/api/system/resources/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resources }),
  }),
  remove: async (resources: ManagedModelResourceId[]) => requestJson<ResourceRemovalResult>(`${CONTROL_ORIGIN}/api/system/resources/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resources, confirmation: 'PERMANENT_REMOVE' }),
    timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS,
  }),
  storageStatus: async () => requestJson<StorageStatusPayload>(`${CONTROL_ORIGIN}/api/system/storage`),
  cleanupStorage: async (targets: Array<Exclude<StorageCategoryId, 'visual_frames'>>) => requestJson<StorageCleanupResult>(`${CONTROL_ORIGIN}/api/system/storage/cleanup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targets, confirmation: 'PERMANENT_CLEAN' }),
  }),
  pickLocalModel: async (modelType: PetImportableModelType) => requestJson<LocalModelPickerResponse>(`${CONTROL_ORIGIN}/api/pet/model/pick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ modelType }),
  }),
  importLocalModel: async (sourcePath: string, modelType: PetImportableModelType) => requestJson<LocalModelImportResponse>(`${CONTROL_ORIGIN}/api/pet/model/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sourcePath, modelType }),
    timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS,
  }),
  prepareSoulx: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/soulx/download`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
  importSoulxReference: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/soulx/reference`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
  prepareSherpa: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/sherpa/download`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
  prepareSherpaOnline: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/sherpa-online/download`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
  prepareEmbedding: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/embedding/prefetch`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
  prepareTts: async () => requestJson<ResourceCommandResult>(`${CONTROL_ORIGIN}/api/system/resources/tts/prefetch`, { method: 'POST', timeoutMs: RESOURCE_OPERATION_TIMEOUT_MS }),
}

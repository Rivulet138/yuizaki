import { contextBridge, ipcRenderer } from 'electron'
import type { ScreenCaptureEncodingOptions } from '../shared/types'
import type {
  PetControlConfigPatch,
  PetControlState,
  PetDisplayInfo,
  PetLipSyncLevelPayload,
  PetLipSyncLevelSource,
  PetLipSyncViseme,
  PetLipSyncVisemePayload,
  PetModelCatalogPayload,
  PetPlacement,
  PetPlacementPreset,
  PetModelType,
} from '../shared/pet-control'
import type {
  LocalModelImportResponse,
  LocalModelPickerImportResponse,
  LocalModelPickerResponse,
  PetModelImportMode,
} from '../shared/resource-manager'
import type {
  InputBindingSettingsPatch,
  InputBindingSnapshot,
} from '../shared/input-bindings'

const callbackMap = new WeakMap<(...args: any[]) => void, (...args: any[]) => void>()

const sendLipSyncLevel = (level: number, active: boolean, source: PetLipSyncLevelSource) =>
  ipcRenderer.send('ui:set-lipsync-level', {
    level,
    active,
    source,
  } satisfies PetLipSyncLevelPayload)

const api = {
  python: {
    start: () => ipcRenderer.invoke('python:start'),
    stop: () => ipcRenderer.invoke('python:stop'),
    health: () => ipcRenderer.invoke('python:health'),
  },

  window: {
    show: () => ipcRenderer.invoke('window:show'),
    hide: () => ipcRenderer.invoke('window:hide'),
    toggle: () => ipcRenderer.invoke('window:toggle'),
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
  },

  interact: {
    toggle: () => ipcRenderer.invoke('pet:toggle-interact'),
    enable: () => ipcRenderer.send('pet:interact-enable'),
    disable: () => ipcRenderer.send('pet:interact-disable'),
  },

  pet: {
    getState: () => ipcRenderer.invoke('pet:get-state') as Promise<PetControlState>,
    getCatalog: () => ipcRenderer.invoke('pet:get-catalog') as Promise<PetModelCatalogPayload>,
    getDisplays: () => ipcRenderer.invoke('pet:get-displays') as Promise<{ activeDisplayId: number | null; displays: PetDisplayInfo[] }>,
    getPlacementPresets: () => ipcRenderer.invoke('pet:get-placement-presets') as Promise<{ presets: PetPlacementPreset[] }>,
    getModelCatalog: () => ipcRenderer.invoke('pet:get-catalog') as Promise<PetModelCatalogPayload>,
    setModelType: (modelType: PetModelType) =>
      ipcRenderer.invoke('pet:update-config', { modelType }) as Promise<PetControlState>,
    setModelSelection: (modelId: string | null, modelType?: PetModelType) =>
      ipcRenderer.invoke('pet:update-config', { modelId, modelType }) as Promise<PetControlState>,
    setModel: (modelId: string | null) =>
      ipcRenderer.invoke('pet:set-model', modelId) as Promise<PetControlState>,
    triggerEmotion: (emotionId: string) =>
      ipcRenderer.invoke('pet:trigger-emotion', emotionId) as Promise<{ success: boolean }>,
    updateConfig: (patch: PetControlConfigPatch) =>
      ipcRenderer.invoke('pet:update-config', patch) as Promise<PetControlState>,
    snapBottomRight: () =>
      ipcRenderer.invoke('pet:snap-bottom-right') as Promise<PetControlState>,
    place: (placement: Exclude<PetPlacement, 'free'>, displayId?: number | null) =>
      ipcRenderer.invoke('pet:place', { placement, displayId }) as Promise<PetControlState>,
    setInteractMode: (enabled: boolean) =>
      ipcRenderer.invoke('pet:set-interact-mode', enabled) as Promise<PetControlState>,
    setLocked: (enabled: boolean) =>
      ipcRenderer.invoke('pet:set-locked', enabled) as Promise<PetControlState>,
    setClickThrough: (enabled: boolean) =>
      ipcRenderer.invoke('pet:set-click-through', enabled) as Promise<PetControlState>,
    reloadRenderer: () =>
      ipcRenderer.invoke('pet:reload-renderer') as Promise<{ success: boolean }>,
    setVisible: (visible: boolean) =>
      ipcRenderer.invoke('pet:set-visible', visible) as Promise<{ success: boolean; visible: boolean }>,
    pickLocalModel: (modelType: PetModelImportMode) =>
      ipcRenderer.invoke('pet:pick-local-model', modelType) as Promise<LocalModelPickerResponse>,
    importLocalModel: (sourcePath: string, modelType: PetModelImportMode) =>
      ipcRenderer.invoke('pet:import-local-model', { sourcePath, modelType }) as Promise<LocalModelImportResponse>,
    importLocalModelFromPicker: (modelType: PetModelImportMode) =>
      ipcRenderer.invoke('pet:import-local-model-from-picker', modelType) as Promise<LocalModelPickerImportResponse>,
    deleteLocalModel: (modelId: string) =>
      ipcRenderer.invoke('pet:delete-local-model', modelId) as Promise<
        | { success: true; state: PetControlState; catalog: PetModelCatalogPayload; modelRoots: { live2d: string; vrm: string } }
        | { success: false; error: string }
      >,
    setRealtimeLipSync: (level: number, active: boolean) =>
      sendLipSyncLevel(level, active, 'realtime'),
    setTtsLipSync: (level: number, active: boolean) =>
      sendLipSyncLevel(level, active, 'tts-pcm'),
    setTtsViseme: (viseme: PetLipSyncViseme, weight: number, active: boolean) =>
      ipcRenderer.send('ui:set-lipsync-viseme', {
        viseme,
        weight,
        active,
        source: 'tts-pcm',
      } satisfies PetLipSyncVisemePayload),
  },

  live2d: {
    triggerExpression: (name: string) => ipcRenderer.send('ui:trigger-expression', { name }),
    triggerAnimation: (name: string) => ipcRenderer.send('ui:trigger-animation', { name }),
    triggerMotion: (group: string, index: number = 0) =>
      ipcRenderer.send('ui:trigger-animation', { group, index }),
  },

  screen: {
    listDisplays: () => ipcRenderer.invoke('screen:list-displays') as Promise<Array<{
      index: number
      id: number
      label: string
      width: number
      height: number
      scaleFactor: number
      isPrimary: boolean
    }>>,
    capture: (displayIndex: number = 0, options: ScreenCaptureEncodingOptions = {}) =>
      ipcRenderer.invoke('screen:capture', { displayIndex, ...options }),
    ocr: (displayIndex: number = 0) =>
      ipcRenderer.invoke('screen:ocr', { displayIndex }),
    captureRegion: (
      x: number,
      y: number,
      width: number,
      height: number,
      displayIndex: number = 0,
      options: ScreenCaptureEncodingOptions = {},
    ) =>
      ipcRenderer.invoke('screen:capture-region', {
        displayIndex,
        x,
        y,
        width,
        height,
        ...options,
      }),
  },

  shell: {
    openExternal: (url: string) => ipcRenderer.invoke('shell:open-external', url),
  },

  auth: {
    hasSummaryAdminToken: () => ipcRenderer.invoke('auth:has-summary-admin-token') as Promise<{ hasToken: boolean }>,
    setSummaryAdminToken: (token: string) => ipcRenderer.invoke('auth:set-summary-admin-token', token) as Promise<{ ok: boolean; hasToken: boolean }>,
    clearSummaryAdminToken: () => ipcRenderer.invoke('auth:clear-summary-admin-token') as Promise<{ ok: boolean }>,
  },

  runtime: {
    getResourceSnapshot: () => ipcRenderer.invoke('runtime:get-resource-snapshot') as Promise<{
      measuredAt: string
      cacheBytes: number
      totalPrivateKb: number
      processes: Array<{
        pid: number
        type: string
        privateKb: number
        workingSetKb: number
        peakWorkingSetKb: number
      }>
    }>,
    clearSessionCache: () => ipcRenderer.invoke('runtime:clear-session-cache') as Promise<{
      ok: boolean
      cacheBytesBefore: number
      cacheBytesAfter: number
      clearedBytes: number
    }>,
  },

  inputBindings: {
    get: () => ipcRenderer.invoke('input-bindings:get') as Promise<InputBindingSnapshot>,
    update: (patch: InputBindingSettingsPatch) =>
      ipcRenderer.invoke('input-bindings:update', patch) as Promise<InputBindingSnapshot>,
    reset: () => ipcRenderer.invoke('input-bindings:reset') as Promise<InputBindingSnapshot>,
  },

  on: (channel: string, callback: (...args: any[]) => void) => {
    const validChannels = [
      'shortcut:start-mic',
      'shortcut:stop-mic',
      'shortcut:toggle-mic',
      'shortcut:toggle-vision',
      'panel:open-tab',
      'pet:position-updated',
      'pet:expression-updated',
      'pet:animation-triggered',
    ]

    if (validChannels.includes(channel)) {
      const wrapped = (_: unknown, ...args: any[]) => callback(...args)
      callbackMap.set(callback, wrapped)
      ipcRenderer.on(channel, wrapped)
    }
  },

  off: (channel: string, callback: (...args: any[]) => void) => {
    const wrapped = callbackMap.get(callback)
    if (wrapped) {
      ipcRenderer.removeListener(channel, wrapped)
      callbackMap.delete(callback)
    }
  },
}

contextBridge.exposeInMainWorld('petApi', api)

declare global {
  interface Window {
    petApi: typeof api
  }
}

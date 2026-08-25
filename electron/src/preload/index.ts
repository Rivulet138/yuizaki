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
import type { E2EActivationProof, E2ERendererControlRequest } from '../shared/e2e-preload'
import type {
  ComputerUseBridgeResult,
  ComputerUseBackendResponse,
  ComputerUsePreviewRequest,
} from '../shared/computer-use'
import type { PerceptionBridgeResult } from '../shared/authorized-perception'
import type {
  DesktopActionResult,
  DesktopActionStatus,
} from '../shared/desktop-action'
import type {
  OnboardingProbeRequest,
  OnboardingReadinessSnapshot,
  OnboardingRepairRequest,
  OnboardingRetryRequest,
  OnboardingCancelRunRequest,
  OnboardingDeviceProbeReport,
} from '../shared/onboarding-readiness'

const callbackMap = new WeakMap<(...args: any[]) => void, (...args: any[]) => void>()

const sendLipSyncLevel = (level: number, active: boolean, source: PetLipSyncLevelSource) =>
  ipcRenderer.send('ui:set-lipsync-level', {
    level,
    active,
    source,
  } satisfies PetLipSyncLevelPayload)

const isActivationProof = (value: unknown): value is E2EActivationProof => (
  Boolean(value && typeof value === 'object' && typeof (value as E2EActivationProof).proof === 'string'
    && (value as E2EActivationProof).proof.length > 0)
)

const createE2EPreloadApi = (token: string, activation: unknown) => {
  if (!token || !isActivationProof(activation)) return null
  const proof = activation.proof
  const invokeControl = (channel: string, payload?: unknown) => ipcRenderer.invoke(channel, token, proof, payload)
  return Object.freeze({
    voiceSequence: (payload: unknown) => invokeControl('e2e:voice-sequence', payload),
    pauseHealthPolling: () => invokeControl('e2e:pause-health-polling'),
    pollHealthOnce: () => invokeControl('e2e:poll-health-once'),
    resumeHealthPolling: () => invokeControl('e2e:resume-health-polling'),
    sampleVisualOnce: () => invokeControl('e2e:sample-visual-once'),
    pauseCompanionPolling: () => invokeControl('e2e:pause-companion-polling'),
    pollCompanionOnce: () => invokeControl('e2e:poll-companion-once'),
    resumeCompanionPolling: () => invokeControl('e2e:resume-companion-polling'),
    advanceCompanionCooldown: () => invokeControl('e2e:advance-companion-cooldown'),
    pauseHeartbeat: () => invokeControl('e2e:pause-heartbeat'),
    emitHeartbeatOnce: () => invokeControl('e2e:emit-heartbeat-once'),
    teardownRuntime: () => invokeControl('e2e:teardown-runtime'),
    onControl: (handler: (request: E2ERendererControlRequest) => unknown | Promise<unknown>) => {
      const wrapped = (_event: Electron.IpcRendererEvent, request: E2ERendererControlRequest) => {
        void Promise.resolve()
          .then(() => handler(request))
          .then(
            (result) => ipcRenderer.send('e2e:renderer-control-result', token, proof, request.requestId, { ok: true, result }),
            (error: unknown) => ipcRenderer.send('e2e:renderer-control-result', token, proof, request.requestId, {
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            }),
          )
      }
      ipcRenderer.on('e2e:renderer-control', wrapped)
      return () => ipcRenderer.off('e2e:renderer-control', wrapped)
    },
  })
}

const createSandboxedE2EApi = () => {
  const token = process.env['YUIZAKI_E2E_TOKEN']?.trim() ?? ''
  const argumentToken = process.argv
    .find((argument) => argument.startsWith('--yuizaki-e2e-token='))
    ?.slice('--yuizaki-e2e-token='.length) ?? ''
  if (process.env['YUIZAKI_E2E'] !== '1' || !token || argumentToken !== token) return null
  const activation = ipcRenderer.sendSync('e2e:activate', token) as unknown
  return createE2EPreloadApi(token, activation)
}

const e2eApi = createSandboxedE2EApi()

const api = {
  onboarding: Object.freeze({
    snapshot: () => ipcRenderer.invoke('onboarding:snapshot') as Promise<OnboardingReadinessSnapshot>,
    startBackend: () => ipcRenderer.invoke('onboarding:start-backend') as Promise<OnboardingReadinessSnapshot>,
    cancelBackend: () => ipcRenderer.invoke('onboarding:cancel-backend') as Promise<OnboardingReadinessSnapshot>,
    cancelRun: (request: OnboardingCancelRunRequest) =>
      ipcRenderer.invoke('onboarding:cancel-run', request) as Promise<OnboardingReadinessSnapshot>,
    reportDeviceProbe: (report: OnboardingDeviceProbeReport) =>
      ipcRenderer.invoke('onboarding:report-device-probe', report) as Promise<OnboardingReadinessSnapshot>,
    runProbe: (request: OnboardingProbeRequest = {}) =>
      ipcRenderer.invoke('onboarding:run-probe', request) as Promise<OnboardingReadinessSnapshot>,
    retry: (request: OnboardingRetryRequest) =>
      ipcRenderer.invoke('onboarding:retry', request) as Promise<OnboardingReadinessSnapshot>,
    runRepair: (request: OnboardingRepairRequest) =>
      ipcRenderer.invoke('onboarding:run-repair', request) as Promise<OnboardingReadinessSnapshot>,
  }),
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
    beginAdjustment: () =>
      ipcRenderer.invoke('pet:begin-adjustment') as Promise<PetControlState>,
    completeAdjustment: () =>
      ipcRenderer.invoke('pet:complete-adjustment') as Promise<PetControlState>,
    cancelAdjustment: () =>
      ipcRenderer.invoke('pet:cancel-adjustment') as Promise<PetControlState>,
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

  computerUse: {
    preview: (payload: ComputerUsePreviewRequest) =>
      ipcRenderer.invoke('computer-use:preview', payload) as Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>>,
    emergencyStop: () =>
      ipcRenderer.invoke('computer-use:emergency-stop') as Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>>,
    status: () =>
      ipcRenderer.invoke('computer-use:status') as Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>>,
  },
  desktopAction: Object.freeze({
    status: () =>
      ipcRenderer.invoke('desktop-action:status') as Promise<DesktopActionResult<DesktopActionStatus>>,
    enable: () =>
      ipcRenderer.invoke('desktop-action:enable') as Promise<DesktopActionResult<DesktopActionStatus>>,
    disable: () =>
      ipcRenderer.invoke('desktop-action:disable') as Promise<DesktopActionResult<DesktopActionStatus>>,
    rearm: () =>
      ipcRenderer.invoke('desktop-action:rearm') as Promise<DesktopActionResult<DesktopActionStatus>>,
    manageAuthorization: () =>
      ipcRenderer.invoke('desktop-action:manage-authorization') as Promise<DesktopActionResult<DesktopActionStatus>>,
  }),
  perception: Object.freeze({
    collectScreenshot: (sessionId: string) => ipcRenderer.invoke('perception:collect-screenshot', sessionId) as Promise<PerceptionBridgeResult>,
    collectTargetWindow: (sessionId: string) => ipcRenderer.invoke('perception:collect-target-window', sessionId) as Promise<PerceptionBridgeResult>,
    collectActiveApplication: (sessionId: string) => ipcRenderer.invoke('perception:collect-active-application', sessionId) as Promise<PerceptionBridgeResult>,
    collectSelectedFile: (sessionId: string) => ipcRenderer.invoke('perception:collect-selected-file', sessionId) as Promise<PerceptionBridgeResult>,
    collectClipboard: (sessionId: string) => ipcRenderer.invoke('perception:collect-clipboard', sessionId) as Promise<PerceptionBridgeResult>,
    collectOcr: (sessionId: string) => ipcRenderer.invoke('perception:collect-ocr', sessionId) as Promise<PerceptionBridgeResult>,
  }),

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
  ...(e2eApi ? { e2e: e2eApi } : {}),
}

contextBridge.exposeInMainWorld('petApi', api)

declare global {
  interface Window {
    petApi: typeof api
  }
}

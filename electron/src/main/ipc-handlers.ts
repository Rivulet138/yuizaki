import { app, ipcMain, nativeImage, screen, shell } from 'electron'
import type { BrowserWindow, Display, NativeImage, Rectangle, WebContents } from 'electron'
import { logger } from './logger'
import { assertTrustedIpcSender } from './trusted-renderer-url'
import { isPetLipSyncViseme } from '../shared/pet-control'
import type { AvatarCapabilitySnapshot, AvatarCommandResult } from '../shared/avatar-command'
import type {
  PetControlConfigPatch,
  PetControlState,
  PetDisplayInfo,
  PetLipSyncLevelPayload,
  PetLipSyncVisemePayload,
  PetModelCatalogPayload,
  PetModelDefinition,
  PetPlacementPreset,
  PetRendererStatePayload,
} from '../shared/pet-control'
import type {
  DesktopPetEventDispatchResult,
  DesktopPetEventDispatchTarget,
  DesktopPetEventName,
  DesktopPetEventRecord,
} from '../shared/plugin'
import type { PluginRegistry } from './plugin-registry'
import type {
  LocalModelImportResponse,
  LocalModelPickerImportResponse,
  LocalModelPickerResponse,
  LocalModelRoots,
  PetModelImportMode,
} from '../shared/resource-manager'
import {
  deleteLocalModelById,
  importLocalModelFromPath,
  isModelImportMode,
  pickLocalModelSource,
  refreshPetCatalog,
  type PetModelMutationContext,
} from './pet-local-model-import'
import type {
  InputBindingSettingsPatch,
  InputBindingSnapshot,
} from '../shared/input-bindings'
import type { ScreenCaptureEncodingOptions } from '../shared/types'
import {
  stopDesktopAutomationWithPerceptionFence,
} from './perception-stop-coordinator'
import {
  applyBlackPrivacyMasks,
  mapLogicalRegionToPixels,
  normalizeLogicalScreenRegion,
} from './screen-privacy-mask'
import type { ComputerUseBridge } from './computer-use-bridge'
import type { AuthorizedPerceptionBridge } from './authorized-perception-bridge'
import type { DesktopActionBridge } from './desktop-action-bridge'
import type { OnboardingReadinessCoordinator } from './onboarding-readiness-coordinator'
import {
  isOnboardingProbeId,
  isOnboardingRepairActionId,
  isOnboardingDeviceProbeReport,
  type OnboardingProbeRequest,
  type OnboardingRetryRequest,
} from '../shared/onboarding-readiness'

export interface IpcContext {
  live2dWindow: {
    sendToRenderer: (channel: string, data: unknown) => void
    setInteractMode: (enabled: boolean) => void
    setLocked: (enabled: boolean) => void
    setClickThrough: (enabled: boolean) => void
    toggleInteract: () => boolean
    setMousePassthrough: (ignore: boolean, forward: boolean) => void
    getDisplays: () => PetDisplayInfo[]
    getBounds: () => { x: number; y: number; width: number; height: number } | null
    show: () => void
    hide: () => void
    reloadRenderer: () => void
    requestPetState: () => void
    handleRendererReady: (sender: WebContents) => boolean
    handleAvatarCapabilities: (sender: WebContents, payload: unknown) => boolean
    handleAvatarCommandResult: (sender: WebContents, payload: unknown) => boolean
    handleLipSyncReady: (sender: WebContents, payload: unknown) => boolean
    getAvatarCapabilities: () => unknown
    requestAvatarCapabilities: () => void
  }
  petWindow: {
    window: BrowserWindow | null
  }
  petStateStore: {
    getState: () => PetControlState
    applyConfigPatch: (patch: PetControlConfigPatch) => PetControlState
    applyRendererState: (payload: PetRendererStatePayload) => PetControlState
    setReady: (ready: boolean) => void
    setInteractMode: (enabled: boolean) => PetControlState
    setVisible: (visible: boolean) => PetControlState
  }
  petModelCatalog: {
    refresh: () => void
    normalizeModelId: (id: string | null | undefined) => string | null
    getDefaultModelId: () => string | null
    getModelById: (id: string | null | undefined) => PetModelDefinition | null
    getModels: () => PetModelDefinition[]
    resolveEmotionTrigger: (modelId: string | null, emotionId: string) => unknown | null
    getCatalog: (modelId: string | null) => PetModelCatalogPayload
    getLocalModelRoots: () => LocalModelRoots
    importLocalLive2dModel: (sourcePath: string) => Promise<PetModelDefinition>
    importLocalVrmModel: (sourcePath: string) => PetModelDefinition
    removeLocalModel: (modelId: string) => boolean
  }
  applyPetStateToRenderer: (state: PetControlState) => void
  normalizePetPatch: (patch: PetControlConfigPatch) => PetControlConfigPatch
  dockPetToBottomRight: () => void
  captureDisplayPng: (display: Display, displayIndex: number) => Promise<Buffer>
  pluginRegistry: PluginRegistry
  backendApiToken: string
  controlOrigin: string
  openPanel: (tab?: string) => Promise<void>
  pythonService: {
    start: () => Promise<void>
    stop: () => Promise<void>
    health: () => Promise<boolean>
  }
  onboardingCoordinator: OnboardingReadinessCoordinator
  inputBindings: {
    getSnapshot: () => InputBindingSnapshot
    update: (patch: InputBindingSettingsPatch) => InputBindingSnapshot | Promise<InputBindingSnapshot>
    reset: () => InputBindingSnapshot | Promise<InputBindingSnapshot>
  }
  computerUseBridge: ComputerUseBridge
  desktopActionBridge: DesktopActionBridge
  perceptionBridge: AuthorizedPerceptionBridge
}

const PET_EVENT_NAMES = new Set<DesktopPetEventName>([
  'onPetClicked',
  'onPetDragged',
  'onPetIdle',
  'onEmotionChanged',
  'onSpeechStart',
  'onSpeechEnd',
  'onToolStart',
  'onToolEnd',
  'requestPetAction',
])
const PET_EVENT_DISPATCH_LIMIT = 4
const PET_EVENT_ROUTE_COOLDOWN_MS = 500
const PET_EVENT_BODY_LIMIT_BYTES = 16 * 1024
const lastPetEventDispatchAt = new Map<string, number>()

const isDesktopPetEventName = (value: unknown): value is DesktopPetEventName =>
  typeof value === 'string' && PET_EVENT_NAMES.has(value as DesktopPetEventName)

const isPlainPayload = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const normalizeDesktopPetEvent = (value: unknown): DesktopPetEventRecord | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const record = value as Record<string, unknown>
  const event = record['event']
  const payload = record['payload']
  if (!isDesktopPetEventName(event) || !isPlainPayload(payload)) {
    return null
  }
  const timestamp = typeof record['timestamp'] === 'string' && record['timestamp'].trim()
    ? record['timestamp']
    : new Date().toISOString()
  return {
    event,
    timestamp,
    payload,
  }
}

const dispatchDesktopPetEventToPlugins = async (
  ctx: IpcContext,
  detail: DesktopPetEventRecord,
): Promise<DesktopPetEventDispatchResult> => {
  const plugins = ctx.pluginRegistry.snapshot().plugins
  const targets = plugins.flatMap((plugin) =>
    (plugin.petEvents ?? [])
      .filter((subscription) => subscription.event === detail.event && typeof subscription.routeId === 'string')
      .map((subscription) => ({
        pluginId: plugin.id,
        routeId: subscription.routeId as string,
        event: subscription.event,
        description: subscription.description,
      })),
  )

  if (targets.length === 0) {
    return { ok: true, event: detail.event, matched: 0, dispatched: 0, skipped: 0, results: [] }
  }

  const now = Date.now()
  const selectedTargets = targets.slice(0, PET_EVENT_DISPATCH_LIMIT)
  const overflow: DesktopPetEventDispatchTarget[] = targets.slice(PET_EVENT_DISPATCH_LIMIT).map((target) => ({
    pluginId: target.pluginId,
    routeId: target.routeId,
    event: target.event,
    status: 'skipped',
    reason: 'dispatch-limit',
  }))

  const results = await Promise.all(selectedTargets.map(async (target): Promise<DesktopPetEventDispatchTarget> => {
    const cooldownKey = `${target.pluginId}:${target.routeId}:${target.event}`
    const lastDispatchedAt = lastPetEventDispatchAt.get(cooldownKey) ?? 0
    if (now - lastDispatchedAt < PET_EVENT_ROUTE_COOLDOWN_MS) {
      return {
        pluginId: target.pluginId,
        routeId: target.routeId,
        event: target.event,
        status: 'skipped',
        reason: 'cooldown',
      }
    }

    const routeUrl = new URL(
      `/api/plugin/${encodeURIComponent(target.pluginId)}/${encodeURIComponent(target.routeId)}`,
      ctx.controlOrigin,
    )
    const body = JSON.stringify({
      ...detail,
      source: 'desktop-pet',
      subscription: {
        event: target.event,
        routeId: target.routeId,
        description: target.description,
      },
    })
    if (Buffer.byteLength(body, 'utf8') > PET_EVENT_BODY_LIMIT_BYTES) {
      return {
        pluginId: target.pluginId,
        routeId: target.routeId,
        event: target.event,
        status: 'skipped',
        reason: 'payload-too-large',
      }
    }

    lastPetEventDispatchAt.set(cooldownKey, now)
    try {
      const response = await fetch(routeUrl, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${ctx.backendApiToken}`,
          'Content-Type': 'application/json',
        },
        body,
      })
      const responseBody = await response.json().catch(() => ({})) as Record<string, unknown>
      if (!response.ok) {
        return {
          pluginId: target.pluginId,
          routeId: target.routeId,
          event: target.event,
          status: 'failed',
          reason: typeof responseBody['error'] === 'string' ? responseBody['error'] : `HTTP ${response.status}`,
        }
      }
      return {
        pluginId: target.pluginId,
        routeId: target.routeId,
        event: target.event,
        status: 'dispatched',
        ...(typeof responseBody['invocationId'] === 'string' ? { invocationId: responseBody['invocationId'] } : {}),
        ...(typeof responseBody['traceId'] === 'string' ? { traceId: responseBody['traceId'] } : {}),
      }
    } catch (error) {
      return {
        pluginId: target.pluginId,
        routeId: target.routeId,
        event: target.event,
        status: 'failed',
        reason: error instanceof Error ? error.message : String(error),
      }
    }
  }))

  const allResults = [...results, ...overflow]
  const dispatched = allResults.filter((item) => item.status === 'dispatched').length
  const skipped = allResults.filter((item) => item.status === 'skipped').length
  return {
    ok: allResults.every((item) => item.status !== 'failed'),
    event: detail.event,
    matched: targets.length,
    dispatched,
    skipped,
    results: allResults,
  }
}

export function registerIpcHandlers(ctx: IpcContext): void {
  registerPythonHandlers(ctx)
  registerOnboardingHandlers(ctx)
  registerWindowControlHandlers(ctx)
  registerPetControlHandlers(ctx)
  registerPetInteractionHandlers(ctx)
  registerPetWindowHandlers(ctx)
  registerUiForwardingHandlers(ctx)
  registerScreenCaptureHandlers(ctx)
  registerShellHandlers()
  registerRuntimeHandlers()
  registerInputBindingHandlers(ctx)
  registerComputerUseHandlers(ctx)
  registerDesktopActionHandlers(ctx)
  registerAuthorizedPerceptionHandlers(ctx)
}

const isExactRecord = (value: unknown, allowed: readonly string[]): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value as Record<string, unknown>).every((key) => allowed.includes(key))

const parseOnboardingProbeRequest = (value: unknown): OnboardingProbeRequest => {
  if (value === undefined) return {}
  if (!isExactRecord(value, ['probeIds'])) throw new Error('Invalid onboarding probe request')
  const probeIds = value['probeIds']
  if (probeIds === undefined) return {}
  if (!Array.isArray(probeIds) || probeIds.length > 12 || !probeIds.every(isOnboardingProbeId)) {
    throw new Error('Invalid onboarding probe IDs')
  }
  return { probeIds: [...new Set(probeIds)] }
}

function registerOnboardingHandlers(ctx: IpcContext): void {
  ipcMain.handle('onboarding:snapshot', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length) throw new Error('snapshot does not accept arguments')
    return ctx.onboardingCoordinator.snapshot()
  })
  ipcMain.handle('onboarding:start-backend', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length) throw new Error('startBackend does not accept arguments')
    return ctx.onboardingCoordinator.startBackend()
  })
  ipcMain.handle('onboarding:cancel-backend', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length) throw new Error('cancelBackend does not accept arguments')
    return ctx.onboardingCoordinator.cancelBackend()
  })
  ipcMain.handle('onboarding:cancel-run', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 1 || !isExactRecord(args[0], ['runId']) || typeof args[0]['runId'] !== 'string' || !args[0]['runId']) {
      throw new Error('Invalid onboarding cancel request')
    }
    return ctx.onboardingCoordinator.cancelRun({ runId: args[0]['runId'] })
  })
  ipcMain.handle('onboarding:report-device-probe', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 1 || !isOnboardingDeviceProbeReport(args[0])) throw new Error('Invalid onboarding device report')
    return ctx.onboardingCoordinator.reportDeviceProbe(args[0])
  })
  ipcMain.handle('onboarding:run-probe', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length > 1) throw new Error('runProbe accepts at most one argument')
    return ctx.onboardingCoordinator.runProbe(parseOnboardingProbeRequest(args[0]))
  })
  ipcMain.handle('onboarding:retry', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 1) throw new Error('retry requires one argument')
    const payload = args[0]
    if (!isExactRecord(payload, ['runId', 'probeIds']) || typeof payload['runId'] !== 'string' || !payload['runId']) {
      throw new Error('Invalid onboarding retry request')
    }
    const probes = parseOnboardingProbeRequest({ ...(payload['probeIds'] === undefined ? {} : { probeIds: payload['probeIds'] }) })
    const request: OnboardingRetryRequest = { runId: payload['runId'], ...probes }
    return ctx.onboardingCoordinator.retry(request)
  })
  ipcMain.handle('onboarding:run-repair', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 1) throw new Error('runRepair requires one argument')
    const payload = args[0]
    if (!isExactRecord(payload, ['actionId']) || !isOnboardingRepairActionId(payload['actionId'])) {
      throw new Error('Unknown onboarding repair action')
    }
    return ctx.onboardingCoordinator.runRepair(payload['actionId'])
  })
}

function registerDesktopActionHandlers(ctx: IpcContext): void {
  ipcMain.handle('desktop-action:status', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 0) return {
      ok: false,
      code: 'DA_INVALID_REQUEST',
      message: 'status does not accept arguments',
      status: ctx.desktopActionBridge.getStatus(),
    }
    return ctx.desktopActionBridge.refreshStatus()
  })
  ipcMain.handle('desktop-action:enable', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 0) return {
      ok: false,
      code: 'DA_INVALID_REQUEST',
      message: 'enable does not accept arguments',
      status: ctx.desktopActionBridge.getStatus(),
    }
    return ctx.desktopActionBridge.enable()
  })
  ipcMain.handle('desktop-action:disable', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 0) return {
      ok: false,
      code: 'DA_INVALID_REQUEST',
      message: 'disable does not accept arguments',
      status: ctx.desktopActionBridge.getStatus(),
    }
    return ctx.desktopActionBridge.disable()
  })
  ipcMain.handle('desktop-action:rearm', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 0) return {
      ok: false,
      code: 'DA_INVALID_REQUEST',
      message: 'rearm does not accept arguments',
      status: ctx.desktopActionBridge.getStatus(),
    }
    return ctx.desktopActionBridge.rearm()
  })
  ipcMain.handle('desktop-action:manage-authorization', (event, ...args: unknown[]) => {
    assertTrustedIpcSender(event)
    if (args.length !== 0) return {
      ok: false,
      code: 'DA_INVALID_REQUEST',
      message: 'manage authorization does not accept arguments',
      status: ctx.desktopActionBridge.getStatus(),
    }
    return ctx.desktopActionBridge.manageAuthorization()
  })
}

function registerAuthorizedPerceptionHandlers(ctx: IpcContext): void {
  const methods = {
    'perception:collect-screenshot': (id: unknown) => ctx.perceptionBridge.collectScreenshot(id),
    'perception:collect-target-window': (id: unknown) => ctx.perceptionBridge.collectTargetWindow(id),
    'perception:collect-active-application': (id: unknown) => ctx.perceptionBridge.collectActiveApplication(id),
    'perception:collect-selected-file': (id: unknown) => ctx.perceptionBridge.collectSelectedFile(id),
    'perception:collect-clipboard': (id: unknown) => ctx.perceptionBridge.collectClipboard(id),
    'perception:collect-ocr': (id: unknown) => ctx.perceptionBridge.collectOcr(id),
  } as const
  for (const [channel, collect] of Object.entries(methods)) {
    ipcMain.handle(channel, (event, sessionId: unknown) => {
      assertTrustedIpcSender(event)
      return collect(sessionId)
    })
  }
}

function registerComputerUseHandlers(ctx: IpcContext): void {
  ipcMain.handle('computer-use:preview', (event, payload: unknown) => {
    assertTrustedIpcSender(event)
    return ctx.computerUseBridge.preview(payload)
  })
  ipcMain.handle('computer-use:emergency-stop', (event) => {
    assertTrustedIpcSender(event)
    return stopDesktopAutomationWithPerceptionFence(
      ctx.computerUseBridge,
      ctx.desktopActionBridge,
      ctx.perceptionBridge,
      'ipc',
    ).then((result) => result.computerUse)
  })
  ipcMain.handle('computer-use:status', (event) => {
    assertTrustedIpcSender(event)
    return ctx.computerUseBridge.refreshStatus()
  })
}

function registerInputBindingHandlers(ctx: IpcContext): void {
  ipcMain.handle('input-bindings:get', (event) => {
    assertTrustedIpcSender(event)
    return ctx.inputBindings.getSnapshot()
  })

  ipcMain.handle('input-bindings:update', (event, patch: InputBindingSettingsPatch) => {
    assertTrustedIpcSender(event)
    return ctx.inputBindings.update(patch && typeof patch === 'object' ? patch : {})
  })

  ipcMain.handle('input-bindings:reset', (event) => {
    assertTrustedIpcSender(event)
    return ctx.inputBindings.reset()
  })
}

function allowTrustedIpcSender(event: Parameters<typeof assertTrustedIpcSender>[0]): boolean {
  try {
    assertTrustedIpcSender(event)
    return true
  } catch (error) {
    logger.warn('Blocked IPC from untrusted renderer:', error)
    return false
  }
}

function registerRuntimeHandlers(): void {
  ipcMain.handle('runtime:get-resource-snapshot', async (event) => {
    assertTrustedIpcSender(event)
    const metrics = app.getAppMetrics().map((metric) => ({
      pid: metric.pid,
      type: metric.type,
      privateKb: metric.memory.privateBytes ?? metric.memory.workingSetSize,
      workingSetKb: metric.memory.workingSetSize,
      peakWorkingSetKb: metric.memory.peakWorkingSetSize,
    }))
    const cacheBytes = await event.sender.session.getCacheSize()
    return {
      measuredAt: new Date().toISOString(),
      cacheBytes,
      totalPrivateKb: metrics.reduce((sum, metric) => sum + Number(metric.privateKb || 0), 0),
      processes: metrics,
    }
  })

  ipcMain.handle('runtime:clear-session-cache', async (event) => {
    assertTrustedIpcSender(event)
    const cacheBytesBefore = await event.sender.session.getCacheSize()
    await event.sender.session.clearCache()
    const cacheBytesAfter = await event.sender.session.getCacheSize()
    return {
      ok: true,
      cacheBytesBefore,
      cacheBytesAfter,
      clearedBytes: Math.max(0, cacheBytesBefore - cacheBytesAfter),
    }
  })
}

function registerPythonHandlers(ctx: IpcContext): void {
  ipcMain.handle('python:start', async (event) => {
    assertTrustedIpcSender(event)
    try {
      await ctx.pythonService.start()
      return { success: true }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  ipcMain.handle('python:stop', async (event) => {
    assertTrustedIpcSender(event)
    try {
      await ctx.pythonService.stop()
      return { success: true }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  ipcMain.handle('python:health', async (event) => {
    assertTrustedIpcSender(event)
    const isHealthy = await ctx.pythonService.health()
    return { healthy: isHealthy }
  })
}

function registerWindowControlHandlers(ctx: IpcContext): void {
  ipcMain.handle('window:show', (event) => {
    assertTrustedIpcSender(event)
    ctx.petWindow.window?.show()
    return Boolean(ctx.petWindow.window)
  })
  ipcMain.handle('window:hide', (event) => {
    assertTrustedIpcSender(event)
    ctx.petWindow.window?.hide()
    return Boolean(ctx.petWindow.window)
  })
  ipcMain.handle('window:toggle', (event) => {
    assertTrustedIpcSender(event)
    const window = ctx.petWindow.window
    if (!window) return false
    if (window.isVisible()) {
      window.hide()
    } else {
      window.show()
    }
    return true
  })
  ipcMain.handle('window:minimize', (event) => {
    assertTrustedIpcSender(event)
    ctx.petWindow.window?.minimize()
    return Boolean(ctx.petWindow.window)
  })
  ipcMain.handle('window:maximize', (event) => {
    assertTrustedIpcSender(event)
    const window = ctx.petWindow.window
    if (!window) return false
    if (window.isMaximized()) {
      window.unmaximize()
    } else {
      window.maximize()
    }
    return true
  })
  ipcMain.handle('window:close', (event) => {
    assertTrustedIpcSender(event)
    ctx.petWindow.window?.close()
    return Boolean(ctx.petWindow.window)
  })
}

function registerPetControlHandlers(ctx: IpcContext): void {
  let adjustmentSnapshot: PetControlState | null = null

  const createModelMutationContext = (): PetModelMutationContext => ({
    petModelCatalog: ctx.petModelCatalog,
    petStateStore: ctx.petStateStore,
    applyStateToLive2D: (state: PetControlState) => {
      ctx.applyPetStateToRenderer(state)
      return ctx.petStateStore.getState()
    },
  })

  ipcMain.handle('pet:toggle-interact', (event) => {
    assertTrustedIpcSender(event)
    const interacting = ctx.live2dWindow.toggleInteract()
    const state = ctx.petStateStore.setInteractMode(interacting)
    return { interacting, state }
  })

  ipcMain.handle('pet:get-state', (event) => {
    assertTrustedIpcSender(event)
    ctx.live2dWindow.requestPetState()
    return ctx.petStateStore.getState()
  })

  ipcMain.handle('pet:get-catalog', (event) => {
    assertTrustedIpcSender(event)
    return refreshPetCatalog(createModelMutationContext()).catalog
  })

  ipcMain.handle('pet:get-displays', (event) => {
    assertTrustedIpcSender(event)
    const displays = ctx.live2dWindow.getDisplays()
    return {
      activeDisplayId: ctx.petStateStore.getState().displayId ?? displays.find((display) => display.primary)?.id ?? null,
      displays,
    }
  })

  ipcMain.handle('pet:get-placement-presets', (event): { presets: PetPlacementPreset[] } => {
    assertTrustedIpcSender(event)
    return {
      presets: [
        { id: 'bottom-right', name: '右下角', placement: 'bottom-right' },
        { id: 'bottom-left', name: '左下角', placement: 'bottom-left' },
        { id: 'top-right', name: '右上角', placement: 'top-right' },
        { id: 'top-left', name: '左上角', placement: 'top-left' },
        { id: 'center', name: '居中', placement: 'center' },
      ],
    }
  })

  ipcMain.handle('pet:set-model', (event, modelId: string | null) => {
    assertTrustedIpcSender(event)
    const requestedModelId = typeof modelId === 'string' ? modelId : null
    const matchedModel = requestedModelId
      ? ctx.petModelCatalog.getModelById(requestedModelId)
      : ctx.petModelCatalog.getModelById(ctx.petModelCatalog.getDefaultModelId())
    if (!matchedModel) {
      return ctx.petStateStore.getState()
    }
    const patch: PetControlConfigPatch = { modelId: matchedModel.id, modelType: matchedModel.type }
    const nextState = ctx.petStateStore.applyConfigPatch(patch)
    ctx.applyPetStateToRenderer(nextState)
    return nextState
  })

  ipcMain.handle('pet:trigger-emotion', (event, emotionId: string) => {
    assertTrustedIpcSender(event)
    const resolvedTrigger = ctx.petModelCatalog.resolveEmotionTrigger(
      ctx.petStateStore.getState().modelId,
      emotionId,
    )
    if (!resolvedTrigger) {
      return { success: false }
    }
    ctx.live2dWindow.sendToRenderer('pet:trigger-emotion', resolvedTrigger)
    return { success: true }
  })

  ipcMain.handle('pet:update-config', (event, patch: PetControlConfigPatch) => {
    assertTrustedIpcSender(event)
    let nextState = ctx.petStateStore.applyConfigPatch(ctx.normalizePetPatch(patch))
    if (patch.clickThrough === true) {
      ctx.live2dWindow.setInteractMode(false)
      nextState = ctx.petStateStore.setInteractMode(false)
    }
    if (typeof patch.locked === 'boolean') {
      ctx.live2dWindow.setLocked(patch.locked)
    }
    if (typeof patch.visible === 'boolean') {
      if (patch.visible) {
        ctx.live2dWindow.show()
      } else {
        ctx.live2dWindow.hide()
      }
    }
    ctx.applyPetStateToRenderer(nextState)
    return nextState
  })

  ipcMain.handle('pet:snap-bottom-right', (event) => {
    assertTrustedIpcSender(event)
    ctx.dockPetToBottomRight()
    return ctx.petStateStore.getState()
  })

  ipcMain.handle('pet:place', (event, payload: { placement?: unknown; displayId?: unknown } | undefined) => {
    assertTrustedIpcSender(event)
    const placement = payload?.placement
    if (
      placement !== 'bottom-right' &&
      placement !== 'bottom-left' &&
      placement !== 'top-right' &&
      placement !== 'top-left' &&
      placement !== 'center'
    ) {
      return ctx.petStateStore.getState()
    }

    const displayId = payload?.displayId === null || payload?.displayId === undefined
      ? null
      : Number(payload.displayId)
    const nextState = ctx.petStateStore.applyConfigPatch({
      placement,
      displayId: displayId !== null && Number.isFinite(displayId) ? Math.trunc(displayId) : null,
    })
    ctx.applyPetStateToRenderer(nextState)
    return ctx.petStateStore.getState()
  })

  ipcMain.handle('pet:set-interact-mode', (event, enabled: boolean) => {
    assertTrustedIpcSender(event)
    const interactMode = Boolean(enabled)
    ctx.live2dWindow.setInteractMode(interactMode)
    let state = ctx.petStateStore.setInteractMode(interactMode)
    if (interactMode) {
      ctx.live2dWindow.show()
      ctx.live2dWindow.setLocked(false)
      ctx.live2dWindow.setClickThrough(false)
      state = ctx.petStateStore.applyConfigPatch({ visible: true, locked: false, clickThrough: false })
      ctx.applyPetStateToRenderer(state)
    }
    return state
  })

  ipcMain.handle('pet:begin-adjustment', (event) => {
    assertTrustedIpcSender(event)
    if (!adjustmentSnapshot) {
      adjustmentSnapshot = ctx.petStateStore.getState()
    }

    ctx.live2dWindow.show()
    ctx.live2dWindow.setLocked(false)
    ctx.live2dWindow.setClickThrough(false)
    ctx.live2dWindow.setInteractMode(true)
    ctx.petStateStore.applyConfigPatch({
      visible: true,
      locked: false,
      clickThrough: false,
    })
    const state = ctx.petStateStore.setInteractMode(true)
    ctx.applyPetStateToRenderer(state)
    return state
  })

  ipcMain.handle('pet:complete-adjustment', (event) => {
    assertTrustedIpcSender(event)
    const previous = adjustmentSnapshot
    adjustmentSnapshot = null
    const clickThrough = previous?.clickThrough ?? true
    const locked = previous?.locked ?? false

    ctx.live2dWindow.setInteractMode(false)
    ctx.live2dWindow.setLocked(locked)
    ctx.live2dWindow.setClickThrough(clickThrough)
    ctx.petStateStore.setInteractMode(false)
    const state = ctx.petStateStore.applyConfigPatch({ clickThrough, locked })
    ctx.applyPetStateToRenderer(state)
    return state
  })

  ipcMain.handle('pet:cancel-adjustment', (event) => {
    assertTrustedIpcSender(event)
    const previous = adjustmentSnapshot
    adjustmentSnapshot = null
    if (!previous) {
      ctx.live2dWindow.setInteractMode(false)
      const state = ctx.petStateStore.setInteractMode(false)
      ctx.applyPetStateToRenderer(state)
      return state
    }

    const restorePatch: PetControlConfigPatch = {
      displayId: previous.displayId,
      scale: previous.scale,
      placement: previous.placement,
      visible: previous.visible,
      clickThrough: previous.clickThrough,
      locked: previous.locked,
      opacity: previous.opacity,
    }
    if (
      previous.placement === 'free' &&
      typeof previous.positionX === 'number' &&
      typeof previous.positionY === 'number'
    ) {
      restorePatch.positionX = previous.positionX
      restorePatch.positionY = previous.positionY
    }

    ctx.live2dWindow.setInteractMode(false)
    ctx.live2dWindow.setLocked(previous.locked)
    ctx.live2dWindow.setClickThrough(previous.clickThrough)
    if (previous.visible) ctx.live2dWindow.show()
    else ctx.live2dWindow.hide()
    ctx.petStateStore.applyConfigPatch(restorePatch)
    const state = ctx.petStateStore.setInteractMode(false)
    ctx.applyPetStateToRenderer(state)
    return state
  })

  ipcMain.handle('pet:set-locked', (event, enabled: boolean) => {
    assertTrustedIpcSender(event)
    const locked = Boolean(enabled)
    ctx.live2dWindow.setLocked(locked)
    const state = ctx.petStateStore.applyConfigPatch({ locked })
    ctx.applyPetStateToRenderer(state)
    return state
  })

  ipcMain.handle('pet:set-click-through', (event, enabled: boolean) => {
    assertTrustedIpcSender(event)
    const clickThrough = Boolean(enabled)
    if (clickThrough) {
      ctx.live2dWindow.setInteractMode(false)
      ctx.petStateStore.setInteractMode(false)
    }
    ctx.live2dWindow.setClickThrough(clickThrough)
    const state = ctx.petStateStore.applyConfigPatch({ clickThrough })
    ctx.applyPetStateToRenderer(state)
    return state
  })

  ipcMain.handle('pet:reload-renderer', (event) => {
    assertTrustedIpcSender(event)
    ctx.live2dWindow.reloadRenderer()
    return { success: true }
  })

  ipcMain.handle('pet:set-visible', (event, enabled: boolean) => {
    assertTrustedIpcSender(event)
    if (enabled) {
      ctx.live2dWindow.show()
    } else {
      ctx.live2dWindow.hide()
    }
    ctx.petStateStore.setVisible(Boolean(enabled))
    return { success: true, visible: Boolean(enabled) }
  })

  ipcMain.handle('pet:pick-local-model', async (event, modelType: unknown): Promise<LocalModelPickerResponse> => {
    assertTrustedIpcSender(event)
    const importMode = isModelImportMode(modelType) ? modelType : 'live2d'
    return pickLocalModelSource(importMode)
  })

  ipcMain.handle('pet:import-local-model', async (
    event,
    payload: { sourcePath?: string; modelType?: unknown } | undefined,
  ): Promise<LocalModelImportResponse> => {
    assertTrustedIpcSender(event)
    const importMode = isModelImportMode(payload?.modelType) ? payload.modelType : 'live2d'
    return importLocalModelFromPath(createModelMutationContext(), payload?.sourcePath ?? '', importMode)
  })

  ipcMain.handle('pet:import-local-model-from-picker', async (
    event,
    modelType: unknown,
  ): Promise<LocalModelPickerImportResponse> => {
    assertTrustedIpcSender(event)
    const importMode: PetModelImportMode = isModelImportMode(modelType) ? modelType : 'live2d'
    const picked = await pickLocalModelSource(importMode)
    if (!picked.sourcePath) {
      return {
        success: false,
        canceled: true,
        modelType: importMode,
        sourcePath: null,
      }
    }

    return {
      ...(await importLocalModelFromPath(createModelMutationContext(), picked.sourcePath, importMode)),
      canceled: false,
      sourcePath: picked.sourcePath,
    }
  })

  ipcMain.handle('pet:delete-local-model', (event, modelId: string) => {
    assertTrustedIpcSender(event)
    const result = deleteLocalModelById(createModelMutationContext(), String(modelId || ''))
    if (!result) {
      return { success: false, error: 'Local model not found' }
    }
    return result
  })

}

function registerPetInteractionHandlers(ctx: IpcContext): void {
  ipcMain.on('pet:renderer-ready', (event) => {
    ctx.live2dWindow.handleRendererReady(event.sender)
  })

  ipcMain.on('pet:avatar-capabilities', (event, payload: AvatarCapabilitySnapshot) => {
    ctx.live2dWindow.handleAvatarCapabilities(event.sender, payload)
  })

  ipcMain.on('pet:avatar-command-result', (event, payload: AvatarCommandResult) => {
    ctx.live2dWindow.handleAvatarCommandResult(event.sender, payload)
  })

  ipcMain.on('pet:lipsync-ready', (event, payload: unknown) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.live2dWindow.handleLipSyncReady(event.sender, payload)
  })

  ipcMain.on('pet:interact-enable', (event) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.live2dWindow.setInteractMode(true)
    ctx.petStateStore.setInteractMode(true)
  })

  ipcMain.on('pet:interact-disable', (event) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.live2dWindow.setInteractMode(false)
    ctx.petStateStore.setInteractMode(false)
  })

  ipcMain.on('pet:open-control-panel', (event) => {
    if (!allowTrustedIpcSender(event)) return
    void ctx.openPanel('pet')
  })

  ipcMain.on('pet:open-chat-center', (event) => {
    if (!allowTrustedIpcSender(event)) return
    void ctx.openPanel('chat')
  })

  ipcMain.on('pet:set-position', (event, data: { x: number; y: number }) => {
    if (!allowTrustedIpcSender(event)) return
    if (ctx.petWindow.window) {
      ctx.petWindow.window.webContents.send('pet:position-updated', data)
    }
  })

  ipcMain.on('pet:drag-window', (event, payload: { deltaX?: number; deltaY?: number } | undefined) => {
    if (!allowTrustedIpcSender(event)) return
    const deltaX = Number(payload?.deltaX ?? 0)
    const deltaY = Number(payload?.deltaY ?? 0)
    const state = ctx.petStateStore.getState()

    if (state.locked || !Number.isFinite(deltaX) || !Number.isFinite(deltaY)) {
      return
    }

    const workArea = screen.getPrimaryDisplay().workArea
    const currentX = state.positionX ?? workArea.x + workArea.width - 160
    const currentY = state.positionY ?? workArea.y + workArea.height - 24
    const nextState = ctx.petStateStore.applyConfigPatch({
      positionX: currentX + Math.round(deltaX),
      positionY: currentY + Math.round(deltaY),
      placement: 'free',
    })
    ctx.applyPetStateToRenderer(nextState)
  })

  ipcMain.on('pet:drag-window-end', (event) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.applyPetStateToRenderer(ctx.petStateStore.getState())
  })

  ipcMain.on(
    'pet:set-ignore-mouse-events',
    (event, payload: { ignore?: boolean; forward?: boolean } | undefined) => {
      if (!allowTrustedIpcSender(event)) return
      ctx.live2dWindow.setMousePassthrough(Boolean(payload?.ignore), payload?.forward !== false)
    },
  )

  ipcMain.on('pet:save-position', (event, data: { x: number; y: number }) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.petStateStore.applyConfigPatch({
      positionX: data.x,
      positionY: data.y,
      placement: 'free',
    })
  })

  ipcMain.on('pet:save-scale', (event, data: { scale: number }) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.petStateStore.applyConfigPatch({
      scale: data.scale,
    })
  })

  ipcMain.on('pet:state-changed', (event, payload: PetRendererStatePayload) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.petStateStore.applyRendererState(payload)
  })

  ipcMain.handle('pet:dispatch-event', async (event, payload: unknown) => {
    assertTrustedIpcSender(event)
    const detail = normalizeDesktopPetEvent(payload)
    if (!detail) {
      return {
        ok: false,
        matched: 0,
        dispatched: 0,
        skipped: 0,
        results: [],
        error: 'Invalid desktop pet event payload',
      } satisfies DesktopPetEventDispatchResult
    }
    return await dispatchDesktopPetEventToPlugins(ctx, detail)
  })
}

function registerPetWindowHandlers(ctx: IpcContext): void {
  ipcMain.on('pet:set-expression', (event, data: { name: string }) => {
    if (!allowTrustedIpcSender(event)) return
    if (ctx.petWindow.window) {
      ctx.petWindow.window.webContents.send('pet:expression-updated', data)
    }
  })

  ipcMain.on('pet:play-animation', (event, data: { name: string }) => {
    if (!allowTrustedIpcSender(event)) return
    if (ctx.petWindow.window) {
      ctx.petWindow.window.webContents.send('pet:animation-triggered', data)
    }
  })
}

function registerUiForwardingHandlers(ctx: IpcContext): void {
  ipcMain.on('ui:trigger-expression', (event, data: { name: string }) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.live2dWindow.sendToRenderer('pet:trigger-expression', data)
  })

  ipcMain.on('ui:trigger-animation', (event, data: { name?: string; group?: string; index?: number }) => {
    if (!allowTrustedIpcSender(event)) return
    ctx.live2dWindow.sendToRenderer('pet:trigger-animation', data)
  })

  const normalizeLipSyncLevel = (
    data: Partial<PetLipSyncLevelPayload>,
    forcedSource?: PetLipSyncLevelPayload['source'],
  ): PetLipSyncLevelPayload | null => {
    const parsedLevel = Number(data?.level)
    const source = forcedSource ?? data?.source
    if (
      !Number.isFinite(parsedLevel)
      || typeof data?.active !== 'boolean'
      || (source !== 'realtime' && source !== 'tts-pcm')
    ) return null
    const active = data.active
    return {
      level: active ? Math.max(0, Math.min(1, parsedLevel)) : 0,
      active,
      source,
    }
  }

  ipcMain.on('ui:set-lipsync-level', (event, data: Partial<PetLipSyncLevelPayload>) => {
    if (!allowTrustedIpcSender(event)) return
    const payload = normalizeLipSyncLevel(data)
    if (payload) {
      ctx.live2dWindow.sendToRenderer('pet:lipsync-level', payload)
    }
  })

  ipcMain.on('ui:set-realtime-lipsync', (event, data: Partial<PetLipSyncLevelPayload>) => {
    if (!allowTrustedIpcSender(event)) return
    const payload = normalizeLipSyncLevel(data, 'realtime')
    if (payload) {
      ctx.live2dWindow.sendToRenderer('pet:lipsync-level', payload)
    }
  })

  ipcMain.on('ui:set-lipsync-viseme', (event, data: Partial<PetLipSyncVisemePayload>) => {
    if (!allowTrustedIpcSender(event)) return
    const parsedWeight = Number(data?.weight)
    if (
      typeof data?.active !== 'boolean'
      || data?.source !== 'tts-pcm'
      || !isPetLipSyncViseme(data?.viseme)
      || !Number.isFinite(parsedWeight)
    ) return
    const active = data.active
    ctx.live2dWindow.sendToRenderer('pet:lipsync-viseme', {
      viseme: active ? data.viseme : 'sil',
      weight: active ? Math.max(0, Math.min(1, parsedWeight)) : 0,
      active,
      source: 'tts-pcm',
    } satisfies PetLipSyncVisemePayload)
  })
}

const toPngDataUrl = (buf: Buffer): string => `data:image/png;base64,${buf.toString('base64')}`

interface CapturePrivacyContext {
  target: Display
  viewport: Rectangle
}

function applyPrivacyMasksToImage(
  image: NativeImage,
  options: ScreenCaptureEncodingOptions,
  context?: CapturePrivacyContext,
): NativeImage | null {
  if (!context || !Array.isArray(options.privacyMasks) || options.privacyMasks.length === 0) return image
  const imageSize = image.getSize()
  const masks = options.privacyMasks
    .slice(0, 8)
    .map((mask) => normalizeLogicalScreenRegion(mask, context.target.bounds))
    .filter((mask): mask is Rectangle => Boolean(mask))
    .map((mask) => mapLogicalRegionToPixels(mask, context.viewport, imageSize))
    .filter((mask): mask is Rectangle => Boolean(mask))
  if (masks.length === 0) return image

  const maskedBitmap = applyBlackPrivacyMasks(image.toBitmap(), imageSize, masks)
  const maskedImage = nativeImage.createFromBitmap(maskedBitmap, imageSize)
  return maskedImage.isEmpty() ? null : maskedImage
}

function encodeNativeImageDataUrl(
  source: NativeImage,
  options: ScreenCaptureEncodingOptions = {},
  privacyContext?: CapturePrivacyContext,
): string | null {
  const format = options.format === 'jpeg' ? 'jpeg' : 'png'
  let image = source
  const size = image.getSize()
  const maxWidth = Math.max(320, Math.min(1920, Math.round(options.maxWidth ?? size.width)))
  const maxHeight = Math.max(180, Math.min(1080, Math.round(options.maxHeight ?? size.height)))
  const scale = Math.min(1, maxWidth / Math.max(1, size.width), maxHeight / Math.max(1, size.height))
  if (scale < 1) {
    image = image.resize({
      width: Math.max(1, Math.round(size.width * scale)),
      height: Math.max(1, Math.round(size.height * scale)),
      quality: 'good',
    })
    if (image.isEmpty()) return null
  }

  const maskedImage = applyPrivacyMasksToImage(image, options, privacyContext)
  if (!maskedImage) return null
  image = maskedImage

  if (format === 'jpeg') {
    const quality = Math.max(40, Math.min(90, Math.round(options.quality ?? 72)))
    const encoded = image.toJPEG(quality)
    return `data:image/jpeg;base64,${encoded.toString('base64')}`
  }
  return toPngDataUrl(image.toPNG())
}

function encodeScreenCaptureDataUrl(
  buf: Buffer,
  options: ScreenCaptureEncodingOptions = {},
  privacyContext?: CapturePrivacyContext,
): string | null {
  const hasResizeRequest = options.maxWidth !== undefined || options.maxHeight !== undefined
  const hasPrivacyMasks = Array.isArray(options.privacyMasks) && options.privacyMasks.length > 0
  if (options.format !== 'jpeg' && !hasResizeRequest && !hasPrivacyMasks) return toPngDataUrl(buf)

  const image = nativeImage.createFromBuffer(buf)
  if (image.isEmpty()) return null
  return encodeNativeImageDataUrl(image, options, privacyContext)
}

function resolveDisplay(displayIndex?: number): { display: Display; index: number } | null {
  const displays = screen.getAllDisplays()
  const requestedIndex = displayIndex ?? 0
  const index = displays[requestedIndex] ? requestedIndex : 0
  const display = displays[index]
  return display ? { display, index } : null
}

function cropScreenshotToDataUrl(
  buf: Buffer,
  target: Display,
  payload: { x: number; y: number; width: number; height: number } & ScreenCaptureEncodingOptions,
): string | null {
  const image = nativeImage.createFromBuffer(buf)
  if (image.isEmpty()) {
    return null
  }
  const logicalRegion = normalizeLogicalScreenRegion(payload, target.bounds)
  if (!logicalRegion) {
    return null
  }
  const displayViewport = { x: 0, y: 0, width: target.bounds.width, height: target.bounds.height }
  const pixelRegion = mapLogicalRegionToPixels(logicalRegion, displayViewport, image.getSize())
  if (!pixelRegion) return null
  return encodeNativeImageDataUrl(image.crop(pixelRegion), payload, { target, viewport: logicalRegion })
}

function registerScreenCaptureHandlers(ctx: IpcContext): void {
  ipcMain.handle('screen:list-displays', (event) => {
    assertTrustedIpcSender(event)
    const primaryId = screen.getPrimaryDisplay().id
    return screen.getAllDisplays().map((display, index) => ({
      index,
      id: display.id,
      label: display.label || `显示器 ${index + 1}`,
      width: display.bounds.width,
      height: display.bounds.height,
      scaleFactor: display.scaleFactor,
      isPrimary: display.id === primaryId,
    }))
  })

  ipcMain.handle('screen:capture', async (
    event,
    options?: ({ displayIndex?: number } & ScreenCaptureEncodingOptions) | null,
  ) => {
    assertTrustedIpcSender(event)
    try {
      const resolved = resolveDisplay(options?.displayIndex)
      if (!resolved) {
        return null
      }
      const { display: target, index } = resolved
      const buf = await ctx.captureDisplayPng(target, index)
      return encodeScreenCaptureDataUrl(buf, options ?? undefined, {
        target,
        viewport: { x: 0, y: 0, width: target.bounds.width, height: target.bounds.height },
      })
    } catch (error) {
      logger.error('Screenshot failed:', error)
      return null
    }
  })

  ipcMain.handle(
    'screen:capture-region',
    async (
      event,
      payload: {
        displayIndex?: number
        x: number
        y: number
        width: number
        height: number
      } & ScreenCaptureEncodingOptions,
    ) => {
      assertTrustedIpcSender(event)
      try {
        const resolved = resolveDisplay(payload.displayIndex)
        if (!resolved) {
          return null
        }
        const { display: target, index } = resolved
        const buf = await ctx.captureDisplayPng(target, index)
        return cropScreenshotToDataUrl(buf, target, payload)
      } catch (error) {
        logger.error('Region screenshot failed:', error)
        return null
      }
    },
  )

}

function registerShellHandlers(): void {
  ipcMain.handle('shell:open-external', async (event, url: string) => {
    assertTrustedIpcSender(event)
    const parsed = new URL(String(url || ''))
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('Unsupported external URL protocol')
    }
    await shell.openExternal(parsed.toString())
  })
}

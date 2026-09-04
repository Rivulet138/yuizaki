import { app, clipboard, desktopCapturer, dialog, screen, shell } from 'electron'
import path from 'path'
import { readFile, stat } from 'node:fs/promises'
import { randomBytes } from 'node:crypto'
import { ControlServer } from './control-server'
import { Live2DWindow } from './live2d-window'
import { PetStateStore } from './pet-state-store'
import { PetShortcuts } from './shortcuts'
import { PetTray } from './tray'
import { PythonService } from './python'
import { PetWindow, type PetWindowRuntimeOptions } from './window'
import { PetModelCatalog } from './pet-model-catalog'
import { registerIpcHandlers, type IpcContext } from './ipc-handlers'
import { PluginRegistry } from './plugin-registry'
import { loadPluginsFromDisk } from './plugin-loader'
import { PackageLifecycle, type PackageCapability } from './package-lifecycle'
import { createDefaultPackageArtifactStore, type LocalPackageArtifactStore } from './package-artifact-store'
import { createDefaultPackageStateStore, type JsonPackageStateStore } from './package-state-store'
import { createFailClosedPackageKeyAuthority } from './package-trust'
import { recordRuntimeException } from './runtime-diagnostics'
import { BackendApiTokenStore } from './backend-api-token-store'
import { InputBindingStore } from './input-binding-store'
import { resolvePythonApiOrigin } from './http/python-origin'
import { ProviderCredentialStore } from './provider-credential-store'
import {
  DEFAULT_INPUT_BINDINGS,
  mergeInputBindingSettings,
  mouseButtonLabel,
  type InputBindingRegistrationStatus,
  type InputBindingSettings,
  type InputBindingSettingsPatch,
  type InputBindingSnapshot,
} from '../shared/input-bindings'
import type {
  PetControlConfigPatch,
  PetControlState,
} from '../shared/pet-control'
import {
  registerRendererProtocol,
  registerRendererProtocolPrivileges,
} from './renderer-protocol'
import { captureDisplayPng } from './desktop-capture'
import { stopDesktopAutomationWithPerceptionFence } from './perception-stop-coordinator'
import { cancelAllModelResourceTasks, prepareModelResources } from './resource-manager'
import { OnboardingReadinessStore } from './onboarding-readiness-store'
import { OnboardingReadinessCoordinator } from './onboarding-readiness-coordinator'
import {
  ComputerUseBridge,
  createAuthenticatedComputerUseBackendPort,
} from './computer-use-bridge'
import { AuthorizedPerceptionBridge } from './authorized-perception-bridge'
import {
  DesktopActionBridge,
  createAuthenticatedDesktopActionBackendPort,
} from './desktop-action-bridge'
import { fenceDesktopActionsWhenHotkeyUnavailable } from './desktop-action-hotkey-coordinator'
import { rebindInputBindingsWithDesktopActionFence } from './input-binding-rebind-coordinator'
import { configureLinuxDesktop } from './linux-desktop'

registerRendererProtocolPrivileges()
configureLinuxDesktop(app, process.env)

let petWindow: PetWindow
let live2dWindow: Live2DWindow
let petTray: PetTray
let petShortcuts: PetShortcuts
let pythonService: PythonService
let petStateStore: PetStateStore
let controlServer: ControlServer
let petModelCatalog: PetModelCatalog
let pluginRegistry: PluginRegistry
let backendApiTokenStore: BackendApiTokenStore
let inputBindingStore: InputBindingStore
let providerCredentialStore: ProviderCredentialStore
let packageLifecycle: PackageLifecycle
let onboardingCoordinator: OnboardingReadinessCoordinator
let computerUseBridge: ComputerUseBridge
let desktopActionBridge: DesktopActionBridge
let perceptionBridge: AuthorizedPerceptionBridge
let inputBindingStatus: InputBindingRegistrationStatus = {
  mouseHookAvailable: false,
  pushToTalkActive: false,
  keyboard: { interact: false, lock: false, openPanel: false, toggleVision: false, emergencyStop: false },
  errors: [],
}
let ipcReady = false
let isQuitting = false
const browserOnly = process.env['YUIZAKI_BROWSER_ONLY'] === '1'

const togglePetLock = () => {
  const nextState = petStateStore.applyConfigPatch({ locked: !petStateStore.getState().locked })
  live2dWindow.setLocked(nextState.locked)
  applyPetStateToRenderer(nextState)
}

const togglePetInteract = () => {
  const interactMode = live2dWindow.toggleInteract()
  let nextState = petStateStore.setInteractMode(interactMode)
  if (interactMode) {
    live2dWindow.show()
    live2dWindow.setLocked(false)
    live2dWindow.setClickThrough(false)
    nextState = petStateStore.applyConfigPatch({ visible: true, locked: false, clickThrough: false })
  }
  applyPetStateToRenderer(nextState)
}

const togglePetClickThrough = () => {
  const clickThrough = !petStateStore.getState().clickThrough
  let nextState = petStateStore.applyConfigPatch({ clickThrough })
  if (clickThrough) {
    live2dWindow.setInteractMode(false)
    petStateStore.setInteractMode(false)
    nextState = petStateStore.applyConfigPatch({ clickThrough: true })
  }
  live2dWindow.setClickThrough(nextState.clickThrough)
  applyPetStateToRenderer(nextState)
}

const hasSingleInstanceLock = app.requestSingleInstanceLock()

if (!hasSingleInstanceLock) {
  app.quit()
}

function buildPanelRuntimeOptions(tab?: string): PetWindowRuntimeOptions {
  return {
    controlOrigin: controlServer.panelUrl.replace(/\/$/, ''),
    apiOrigin: resolvePythonApiOrigin(),
    controlToken: controlServer.getControlToken(),
    ...(tab ? { tab } : {}),
  }
}

async function openPanel(tab?: string): Promise<void> {
  if (browserOnly) {
    const browserUrl = new URL(controlServer.panelUrl)
    browserUrl.searchParams.set('browser_only', '1')
    controlServer.authorizePanelUrl(browserUrl)
    const normalizedTab = tab === 'companion' ? 'chat' : (tab || 'chat')
    browserUrl.hash = `/w/default/${normalizedTab}`
    await shell.openExternal(browserUrl.toString())
    return
  }
  if (!petWindow.window) {
    petWindow.create(buildPanelRuntimeOptions(tab))
  }
  if (tab) {
    petWindow.send('panel:open-tab', tab)
  }
  petWindow.show()
}

function toggleVoiceConversation(): void {
  sendVoiceShortcut('shortcut:toggle-mic')
}

function sendVoiceShortcut(channel: 'shortcut:start-mic' | 'shortcut:stop-mic' | 'shortcut:toggle-mic'): void {
  if (!petWindow?.window) {
    petWindow?.create(buildPanelRuntimeOptions('chat'))
  }
  petWindow?.send(channel)
}

function refreshTrayVoiceBinding(settings: InputBindingSettings): void {
  petTray?.setVoiceBindingStatus(
    `按住${mouseButtonLabel(settings.pushToTalk.mouseButton)}说话`,
    inputBindingStatus.pushToTalkActive,
    live2dWindow,
  )
}

async function applyInputBindings(settings: InputBindingSettings): Promise<InputBindingSnapshot> {
  inputBindingStatus = await rebindInputBindingsWithDesktopActionFence(
    settings,
    petShortcuts,
    desktopActionBridge,
  )
  fenceDesktopActionsWhenHotkeyUnavailable(inputBindingStatus, desktopActionBridge)
  refreshTrayVoiceBinding(settings)
  return { settings, status: inputBindingStatus }
}

async function updateInputBindings(patch: InputBindingSettingsPatch): Promise<InputBindingSnapshot> {
  const settings = mergeInputBindingSettings(inputBindingStore.get(), patch)
  const snapshot = await applyInputBindings(settings)
  inputBindingStore.update(patch)
  return snapshot
}

async function resetInputBindings(): Promise<InputBindingSnapshot> {
  const settings = structuredClone(DEFAULT_INPUT_BINDINGS)
  const snapshot = await applyInputBindings(settings)
  inputBindingStore.reset()
  return snapshot
}

function dockPetToBottomRight(): void {
  const nextState = petStateStore.dockBottomRight()
  applyPetStateToRenderer(nextState)
}

function setPetVisible(visible: boolean): void {
  petStateStore.setVisible(visible)
  if (visible) {
    live2dWindow.show()
  } else {
    live2dWindow.hide()
  }
  petTray?.refresh(live2dWindow)
}

async function createApp(): Promise<void> {
  const hostPerceptionToken = process.env['YUIZAKI_HOST_PERCEPTION_TOKEN']?.trim() || randomBytes(32).toString('base64url')
  const hostDesktopActionToken = randomBytes(32).toString('base64url')
  petWindow = new PetWindow()
  live2dWindow = new Live2DWindow()
  petTray = new PetTray()
  pluginRegistry = new PluginRegistry()
  backendApiTokenStore = new BackendApiTokenStore(path.join(app.getPath('userData'), 'auth'))
  providerCredentialStore = new ProviderCredentialStore(path.join(app.getPath('userData'), 'credentials'))
  providerCredentialStore.migratePlaintextSettings(path.resolve(__dirname, '../../../python/config/settings.json'))
  providerCredentialStore.migratePlaintextConnectorState(path.resolve(__dirname, '../../../python/data/message_connectors.json'))
  inputBindingStore = new InputBindingStore(path.join(app.getPath('userData'), 'input'))
  const packageStateStore: JsonPackageStateStore = createDefaultPackageStateStore(app.getPath('userData'))
  const packageArtifactStore: LocalPackageArtifactStore = createDefaultPackageArtifactStore(app.getPath('userData'))
  const packageCapabilities: ReadonlySet<PackageCapability> = new Set(['voice', 'avatar', 'skill', 'workflow', 'memory-sync'])
  const packageKeyAuthority = createFailClosedPackageKeyAuthority()
  // No install IPC or network source is exposed yet. Keep lifecycle inert until a
  // trusted key authority, artifact download policy, and health checks are wired.
  packageLifecycle = new PackageLifecycle(
    packageArtifactStore,
    packageKeyAuthority.verify.bind(packageKeyAuthority),
    process.versions.electron,
    packageCapabilities,
    packageStateStore,
    () => false,
  )
  for (const reconciliation of packageLifecycle.reconcileAll()) {
    if (reconciliation.status !== 'ready') {
      recordRuntimeException('packageLifecycleReconciliation', JSON.stringify(reconciliation))
    }
  }
  loadPluginsFromDisk(pluginRegistry)
  petModelCatalog = new PetModelCatalog(pluginRegistry)
  petStateStore = new PetStateStore()
  restorePersistedPetModelSelection()
  controlServer = new ControlServer(
    live2dWindow,
    petWindow,
    petStateStore,
    petModelCatalog,
    pluginRegistry,
    path.join(__dirname, '../../dist/renderer'),
    applyPetStateToRenderer,
    providerCredentialStore,
    backendApiTokenStore,
    hostPerceptionToken,
  )
  computerUseBridge = new ComputerUseBridge(createAuthenticatedComputerUseBackendPort(
    resolvePythonApiOrigin(),
    controlServer.getControlToken(),
  ))
  desktopActionBridge = new DesktopActionBridge(
    createAuthenticatedDesktopActionBackendPort(
      resolvePythonApiOrigin(),
      hostDesktopActionToken,
    ),
    {
      isEmergencyHotkeyAvailable: () => inputBindingStatus.keyboard.emergencyStop === true,
      confirmNativeEnable: async (mode, signal) => {
        signal.throwIfAborted()
        const result = await dialog.showMessageBox({
          type: 'warning',
          title: mode === 'rearm' ? 'Rearm desktop action beta' : 'Enable desktop action beta',
          message: mode === 'rearm'
            ? 'Rearm desktop window actions after the emergency stop?'
            : 'Enable desktop window actions for approved agent operations?',
          detail: 'The global emergency-stop shortcut must remain available. This confirmation does not authorize an individual action.',
          buttons: [mode === 'rearm' ? 'Rearm' : 'Enable', 'Cancel'],
          defaultId: 1,
          cancelId: 1,
          noLink: true,
        })
        signal.throwIfAborted()
        return result.response === 0
      },
      selectNativeApp: async (apps, signal) => {
        signal.throwIfAborted()
        const cancelId = apps.length
        const result = await dialog.showMessageBox({
          type: 'question',
          title: 'Authorize desktop application',
          message: 'Choose one application for temporary window actions.',
          detail: 'Authorization expires automatically and is revoked by disable, emergency stop, or loss of the safety lease.',
          buttons: [
            ...apps.map((candidate) => {
              const windows = candidate.windowTitles.slice(0, 2).join(', ')
              return windows ? `${candidate.label}: ${windows}`.slice(0, 120) : candidate.label.slice(0, 120)
            }),
            'Cancel',
          ],
          defaultId: cancelId,
          cancelId,
          noLink: true,
        })
        signal.throwIfAborted()
        return result.response >= 0 && result.response < apps.length
          ? apps[result.response]?.id ?? null
          : null
      },
    },
  )
  perceptionBridge = new AuthorizedPerceptionBridge({
    captureScreenshot: async (signal) => {
      signal.throwIfAborted()
      const target = screen.getPrimaryDisplay()
      const displays = screen.getAllDisplays()
      const displayIndex = Math.max(0, displays.findIndex((display) => display.id === target.id))
      const data = await captureDisplayPng(target, displayIndex, (options) => desktopCapturer.getSources(options))
      signal.throwIfAborted()
      return {
        data,
        displayId: String(target.id),
      }
    },
    captureTargetWindow: async (sourceId, signal) => {
      signal.throwIfAborted()
      const sources = await desktopCapturer.getSources({
        types: ['window'],
        thumbnailSize: { width: 1920, height: 1080 },
        fetchWindowIcons: false,
      })
      signal.throwIfAborted()
      const source = sources.find((candidate) => candidate.id === sourceId)
      if (!source || source.thumbnail.isEmpty()) throw new Error('selected target window is unavailable')
      return { data: source.thumbnail.toPNG(), title: source.name }
    },
    selectTargetWindow: async (signal) => {
      signal.throwIfAborted()
      const sources = (await desktopCapturer.getSources({
        types: ['window'],
        thumbnailSize: { width: 1, height: 1 },
        fetchWindowIcons: false,
      })).slice(0, 20)
      signal.throwIfAborted()
      if (sources.length === 0) return null
      const cancelId = sources.length
      const result = await dialog.showMessageBox({
        type: 'question',
        title: 'Select a window for this request',
        message: 'Choose the window Yuizaki may inspect once.',
        buttons: [...sources.map((source) => source.name.slice(0, 80)), 'Cancel'],
        cancelId,
        defaultId: cancelId,
        noLink: true,
      })
      signal.throwIfAborted()
      const selected = sources[result.response]
      return selected ? { sourceId: selected.id } : null
    },
    selectFile: async (suggestedPath, signal) => {
      signal.throwIfAborted()
      const result = await dialog.showOpenDialog({
        title: 'Select a file for this request',
        properties: ['openFile'],
        ...(suggestedPath ? { defaultPath: suggestedPath } : {}),
      })
      signal.throwIfAborted()
      const selectedPath = result.canceled ? undefined : result.filePaths[0]
      if (!selectedPath) return null
      const info = await stat(selectedPath)
      signal.throwIfAborted()
      if (!info.isFile() || info.size > 128 * 1024) throw new Error('selected file exceeds perception limit')
      const data = await readFile(selectedPath, { signal })
      signal.throwIfAborted()
      return { path: selectedPath, name: path.basename(selectedPath), text: data.toString('utf8') }
    },
    readClipboard: async (signal) => {
      signal.throwIfAborted()
      const text = clipboard.readText('clipboard')
      signal.throwIfAborted()
      return text
    },
    readActiveApplication: async (signal) => {
      const response = await fetch(`${resolvePythonApiOrigin()}/api/perception/active-application`, {
        headers: { 'x-yuizaki-backend-token': controlServer.getControlToken() },
        signal,
      })
      if (!response.ok) throw new Error('active application provider unavailable')
      const payload = await response.json() as { name?: unknown; title?: unknown }
      if (typeof payload.name !== 'string' || !payload.name.trim()) throw new Error('active application identity unavailable')
      return {
        name: payload.name,
        ...(typeof payload.title === 'string' ? { title: payload.title } : {}),
      }
    },
  })
  controlServer.setPerceptionBridge(perceptionBridge)
  petShortcuts = new PetShortcuts(
    live2dWindow,
    togglePetLock,
    () => { void openPanel('companion') },
    () => sendVoiceShortcut('shortcut:start-mic'),
    () => sendVoiceShortcut('shortcut:stop-mic'),
    () => petWindow?.send('shortcut:toggle-vision'),
    () => {
      void stopDesktopAutomationWithPerceptionFence(
        computerUseBridge,
        desktopActionBridge,
        perceptionBridge,
        'shortcut',
      )
    },
  )
  pythonService = new PythonService(
    controlServer.getControlToken(),
    providerCredentialStore.getPythonEnvironment(),
    hostPerceptionToken,
    hostDesktopActionToken,
  )
  controlServer.setPythonProviderEnvironmentUpdater((environment) => {
    pythonService.updateProviderCredentialEnvironment(environment)
  })
  const onboardingStore = new OnboardingReadinessStore(path.join(app.getPath('userData'), 'onboarding'))
  onboardingCoordinator = new OnboardingReadinessCoordinator(
    onboardingStore,
    pythonService,
    resolvePythonApiOrigin(),
    controlServer.getControlToken(),
    {
      avatar: async () => ({
        visible: await live2dWindow.hasVisiblePixels(),
        fallback: false,
      }),
    },
    {
      openPanel,
      prepareResource: async (resourceId) => prepareModelResources([resourceId], petModelCatalog),
      reloadAvatar: () => live2dWindow.reloadRenderer(),
      refreshMcp: async () => {
        const response = await fetch(`${resolvePythonApiOrigin()}/api/system/onboarding/readiness/action`, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-yuizaki-backend-token': controlServer.getControlToken(),
          },
          body: JSON.stringify({ actionId: 'mcp.refresh_existing' }),
        })
        if (!response.ok) throw new Error('MCP refresh failed')
        return response.json()
      },
      openLogs: async () => {
        await shell.openPath(path.join(app.getPath('userData'), 'logs'))
      },
      openInstallGuide: async () => {
        if (app.isPackaged) {
          await shell.openExternal('https://github.com/Rivulet138/yuizaki/blob/main/docs/CONFIGURATION.md')
          return
        }
        await shell.openPath(path.resolve(__dirname, '../../../docs/CONFIGURATION.md'))
      },
    },
  )
  controlServer.setOnboardingCoordinator(onboardingCoordinator)
  setupIPC()

  await controlServer.start()
  live2dWindow.create(controlServer.panelUrl.replace(/\/$/, ''))
  applyPetStateToRenderer(petStateStore.getState())
  if (browserOnly) {
    petStateStore.setVisible(false)
    live2dWindow.hide()
  } else {
    setPetVisible(petStateStore.getState().visible)
  }

  petWindow.create(buildPanelRuntimeOptions())

  const inputSettings = inputBindingStore.get()
  inputBindingStatus = petShortcuts.register(inputSettings)
  fenceDesktopActionsWhenHotkeyUnavailable(inputBindingStatus, desktopActionBridge)

  petTray.create(
    live2dWindow,
    openPanel,
    dockPetToBottomRight,
    togglePetInteract,
    togglePetLock,
    togglePetClickThrough,
    setPetVisible,
    () => petStateStore.getState(),
    () => live2dWindow.reloadRenderer(),
    toggleVoiceConversation,
    {
      label: `按住${mouseButtonLabel(inputSettings.pushToTalk.mouseButton)}说话`,
      available: inputBindingStatus.pushToTalkActive,
    },
  )

  void onboardingCoordinator.startBackend().catch((error: unknown) => {
    console.error('Failed to start Python service:', error)
    return onboardingCoordinator.snapshot()
  })

}

function restorePersistedPetModelSelection(): void {
  const state = petStateStore.getState()
  const restoredModelId = petModelCatalog.resolveModelId(state.modelId)
  const restoredModel = petModelCatalog.getModelById(restoredModelId)
  if (restoredModel) {
    if (state.modelId !== restoredModel.id || state.modelType !== restoredModel.type) {
      petStateStore.applyConfigPatch({ modelId: restoredModel.id, modelType: restoredModel.type })
    }
    return
  }

  const defaultModelId = petModelCatalog.getDefaultModelId()
  const defaultModel = petModelCatalog.getModelById(defaultModelId)
  petStateStore.applyConfigPatch({
    modelId: defaultModelId,
    ...(defaultModel ? { modelType: defaultModel.type } : {}),
  })
}

function normalizePetPatch(patch: PetControlConfigPatch): PetControlConfigPatch {
  const nextPatch: PetControlConfigPatch = { ...patch }

  if ('modelType' in nextPatch && nextPatch.modelType !== 'live2d' && nextPatch.modelType !== 'vrm') {
    delete nextPatch.modelType
  }

  if ('modelId' in nextPatch) {
    if (typeof nextPatch.modelId === 'string') {
      const matchedModelId = petModelCatalog.resolveModelId(nextPatch.modelId)
      const matchedModel = petModelCatalog.getModelById(matchedModelId)
      if (matchedModel) {
        nextPatch.modelId = matchedModel.id
        if (!nextPatch.modelType) {
          nextPatch.modelType = matchedModel.type
        }
      } else {
        delete nextPatch.modelId
        delete nextPatch.modelType
      }
    } else if (nextPatch.modelId !== null) {
      delete nextPatch.modelId
    }
  }

  return nextPatch
}

function applyPetStateToRenderer(state: PetControlState): PetControlState {
  let nextState = state
  const restoredModelId = petModelCatalog.normalizeModelId(state.modelId)
  if (restoredModelId && restoredModelId !== state.modelId) {
    const restoredModel = petModelCatalog.getModelById(restoredModelId)
    nextState = petStateStore.applyConfigPatch({
      modelId: restoredModelId,
      ...(restoredModel ? { modelType: restoredModel.type } : {}),
    })
  }
  const layoutResult = live2dWindow.applyWindowLayout(state)

  if (layoutResult) {
    if (layoutResult.placement === 'free') {
      if (
        state.positionX !== layoutResult.positionX ||
        state.positionY !== layoutResult.positionY ||
        state.placement !== 'free'
      ) {
        nextState = petStateStore.applyConfigPatch({
          positionX: layoutResult.positionX,
          positionY: layoutResult.positionY,
          placement: 'free',
        })
      }
    }
    if (state.displayId !== layoutResult.displayId) {
      nextState = petStateStore.applyConfigPatch({ displayId: layoutResult.displayId })
    }
  }

  live2dWindow.setInteractMode(nextState.interactMode)
  live2dWindow.setClickThrough(nextState.clickThrough)
  live2dWindow.setLocked(nextState.locked)
  live2dWindow.applyPetConfig(petModelCatalog.buildRendererConfig(nextState))
  petTray?.refresh(live2dWindow)

  if (
    nextState.positionX !== state.positionX ||
    nextState.positionY !== state.positionY ||
    nextState.placement !== state.placement ||
    nextState.displayId !== state.displayId ||
    nextState.scale !== state.scale
  ) {
    petStateStore.applyConfigPatch({
      displayId: nextState.displayId,
      positionX: nextState.positionX,
      positionY: nextState.positionY,
      placement: nextState.placement,
      scale: nextState.scale,
    })
  }

  return petStateStore.getState()
}

function setupIPC(): void {
  if (ipcReady) {
    return
  }

  ipcReady = true
  const ipcContext: IpcContext = {
    live2dWindow,
    petWindow,
    petStateStore,
    petModelCatalog,
    applyPetStateToRenderer,
    normalizePetPatch,
    dockPetToBottomRight,
    captureDisplayPng: (display, displayIndex) => captureDisplayPng(
      display,
      displayIndex,
      (options) => desktopCapturer.getSources(options),
    ),
    pluginRegistry,
    backendApiToken: controlServer.getControlToken(),
    controlOrigin: controlServer.panelUrl.replace(/\/$/, ''),
    openPanel,
    pythonService,
    onboardingCoordinator,
    inputBindings: {
      getSnapshot: () => ({ settings: inputBindingStore.get(), status: inputBindingStatus }),
      update: updateInputBindings,
      reset: resetInputBindings,
    },
    computerUseBridge,
    desktopActionBridge,
    perceptionBridge,
  }

  registerIpcHandlers(ipcContext)
}

app.on('second-instance', () => {
  if (browserOnly) {
    void openPanel('chat')
    return
  }
  petWindow?.show()
  setPetVisible(true)
})

app.on('ready', () => {
  if (!hasSingleInstanceLock) return
  registerRendererProtocol()
  void createApp()
})

process.on('uncaughtException', (error) => {
  recordRuntimeException('uncaughtException', error)
})

process.on('unhandledRejection', (reason) => {
  recordRuntimeException('unhandledRejection', reason)
})

app.on('window-all-closed', () => {
  if (isQuitting && process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async () => {
  isQuitting = true
  cancelAllModelResourceTasks()
  computerUseBridge?.dispose()
  desktopActionBridge?.dispose()
  perceptionBridge?.dispose()
  petShortcuts?.unregister()
  petTray?.destroy()
  live2dWindow?.close()
  petWindow?.close()
  await controlServer?.stop()
  await pythonService?.stop()
})

app.on('activate', () => {
  if (!live2dWindow?.window) {
    void createApp()
  }
})
